from flask import Flask, request, render_template, jsonify,send_file,redirect,url_for,session
import boto3
import io
from botocore.exceptions import NoCredentialsError
from datetime import datetime, timedelta, timezone
import json
import os

app = Flask(__name__)
app.config['DEBUG'] = False
app.secret_key = 'your_secret_key_here'

with open('credentials.json', 'r') as f:
    credentials = json.load(f)
AWS_ACCESS_KEY_ID = credentials['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = credentials['AWS_SECRET_ACCESS_KEY']
S3_REGION_NAME = 'ap-south-1'
AWS_REGION='ap-south-1'

config_dir = os.path.dirname(os.path.abspath(__file__))


def load_user_data():
    users_json_path = os.path.join(config_dir, 'users.json')
    try:
        with open(users_json_path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        # Handle the case when the file doesn't exist
        return {"users": []} 

def save_user_data(user_data):
    users_json_path = os.path.join(config_dir, 'users.json')
    with open(users_json_path, 'w') as file:
        json.dump(user_data, file, indent=4)
        
def get_bucket_name(username):
    user_data = load_user_data()
    for user in user_data.get("users", []):
        if user["username"] == username:
            return user["bucket_name"]
    return None

def load_user_data():
    with open("users.json", "r") as file:
        return json.load(file)

def save_user_data(user_data):
    with open("users.json", "w") as file:
        json.dump(user_data, file, indent=4)

@app.route('/logout')
def logout():
    session.pop('username', None) 
    return redirect(url_for('login'))
        
@app.route('/login', methods=['GET', 'POST'])      
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = load_user_data()
        for user in user_data.get("users", []):
            if user["username"] == username and user["password"] == password:
                session['username'] = username
                return redirect(url_for('dashboard'))
        return "Invalid login credentials"
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = load_user_data()
        for user in user_data.get("users", []):
            if user["username"] == username:
                return "Username already exists"
        new_user = {
            "username": username,
            "password": password,
            "bucket_name": f"proj-4529-{username}"
        }
        user_data["users"].append(new_user)
        save_user_data(user_data)
        session['username'] = username
        create_s3_bucket(new_user["bucket_name"])
        return redirect(url_for('dashboard'))
    return render_template('register.html')


def create_s3_bucket(bucket_name):
    s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY, region_name=AWS_REGION)

    try:
        # Check if the bucket already exists
        response = s3.head_bucket(Bucket=bucket_name)
    except NoCredentialsError:
        return "AWS credentials not available"
    except s3.exceptions.NoSuchBucket:
        try:
            # Create the S3 bucket if it doesn't exist
            s3.create_bucket(Bucket=bucket_name)
        except NoCredentialsError:
            return "AWS credentials not available"
        except Exception as e:
            return f"Error creating S3 bucket: {str(e)}"
    except Exception as e:
        return f"Error checking S3 bucket existence: {str(e)}"

    return None
    
def get_bucket_name(username):
    user_data = load_user_data()
    for user in user_data.get("users", []):
        if user["username"] == username:
            return user["bucket_name"]
    return None

@app.route('/dashboard')
def dashboard():
    if 'username' in session:
        s3_bucket_name = get_bucket_name(session['username'])
        s3 = boto3.client('s3', region_name=S3_REGION_NAME)
        
        try:
            files = s3.list_objects_v2(Bucket=s3_bucket_name).get('Contents', [])
            for file in files:
                file['tier'] = get_file_tier(file['LastModified'])
        except NoCredentialsError:
            return "AWS credentials not available"
        
        return render_template('dashboard.html', files=files)
    return redirect(url_for('login'))

def get_file_tier(last_accessed_time):
    current_time = datetime.now(timezone.utc)
    time_difference = current_time - last_accessed_time
    if time_difference < timedelta(seconds=15):
        return "Tier 1"
    elif time_difference < timedelta(seconds=25):
        return "Tier 2"
    else:
        return "Original Tier"

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('login'))
@app.route('/update-access-time/<filename>', methods=['POST'])
def update_access_time(filename):
    if 'username' not in session:
        return jsonify({'message': 'User not authenticated'})

    s3_bucket_name = get_bucket_name(session['username'])
    s3 = boto3.client('s3', region_name=S3_REGION_NAME)

    try:
        # Update the last accessed time for the specified file in the user's bucket
        s3.copy_object(
            CopySource={'Bucket': s3_bucket_name, 'Key': filename},
            Bucket=s3_bucket_name,
            Key=filename,
            MetadataDirective='REPLACE',
            Metadata={'accessed_time': datetime.now(timezone.utc).isoformat()}
        )
    except NoCredentialsError:
        return jsonify({'message': 'AWS credentials not available'})

    return jsonify({'message': 'Access time updated'})

@app.route('/download/<filename>')  # Add a route for file downloads
def download(filename):
    if 'username' not in session:
        return jsonify({'message': 'User not authenticated'})

    s3_bucket_name = get_bucket_name(session['username'])
    s3 = boto3.client('s3', region_name=S3_REGION_NAME)

    try:
        # Download the specified file from the user's bucket
        response = s3.get_object(Bucket=s3_bucket_name, Key=filename)
        file_contents = response['Body'].read()
    except NoCredentialsError:
        return jsonify({'message': 'AWS credentials not available'})

    return send_file(
        io.BytesIO(file_contents),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream'
    )

@app.route('/upload', methods=['POST'])
def upload():
    if 'username' not in session:
        return jsonify({'message': 'User not authenticated'})

    file = request.files['file']

    if not file:
        return jsonify({'message': 'No file provided'})

    s3_bucket_name = get_bucket_name(session['username'])
    s3 = boto3.client('s3', region_name=S3_REGION_NAME)

    try:
        s3.upload_fileobj(file, s3_bucket_name, file.filename)
    except NoCredentialsError:
        return jsonify({'message': 'AWS credentials not available'})

    return redirect(url_for('dashboard'))

@app.route('/delete-file/<filename>', methods=['POST'])
def delete_file(filename):
    if 'username' not in session:
        return jsonify({'message': 'User not authenticated'})

    s3_bucket_name = get_bucket_name(session['username'])
    s3 = boto3.client('s3', region_name=S3_REGION_NAME)

    try:
        # Delete the specified file from the user's bucket
        s3.delete_object(Bucket=s3_bucket_name, Key=filename)
    except NoCredentialsError:
        return jsonify({'message': 'AWS credentials not available'})

    return jsonify({'message': 'File deleted'})

@app.route('/share/<filename>')
def share(filename):
    if 'username' not in session:
        return jsonify({'message': 'User not authenticated'})

    s3_bucket_name = get_bucket_name(session['username'])
    s3 = boto3.client('s3', region_name=S3_REGION_NAME)

    try:
        # Generate a pre-signed URL for the specified file in the user's bucket
        object_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucket_name, 'Key': filename},
            ExpiresIn=300
        )
    except NoCredentialsError:
        return jsonify({'message': 'AWS credentials not available'})

    return render_template('share.html', object_url=object_url)

if __name__ == '__main__':
    app.run(debug=True)
