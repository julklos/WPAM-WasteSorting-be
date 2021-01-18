import ibm_boto3
from ibm_botocore.client import Config
import ibm_botocore.response as br
from cloudant import Cloudant
from cloudant.query import Query
import cloudant
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watson import VisualRecognitionV3
from flask import Flask, render_template, request, jsonify
import atexit
import os
import json
from PIL import Image
import base64
import io
import random

app = Flask(__name__, static_url_path='')
ENCODING = 'utf-8'
db_name = None
client = None
cos = None
db = None
visual_recognition = None

if 'VCAP_SERVICES' in os.environ:
    vcap = json.loads(os.getenv('VCAP_SERVICES'))
    print('Found VCAP_SERVICES')
    if 'cloudantNoSQLDB' in vcap:
        creds = vcap['cloudantNoSQLDB'][0]['credentials']
        user = creds['username']
        password = creds['password']
        url = 'https://' + creds['host']
        client = Cloudant(user, password, url=url, connect=True)
        db = client.create_database(db_name, throw_on_exists=False)
elif "CLOUDANT_URL" in os.environ:
    client = Cloudant(os.environ['CLOUDANT_USERNAME'], os.environ['CLOUDANT_PASSWORD'], url=os.environ['CLOUDANT_URL'], connect=True)
    db = client.create_database(db_name, throw_on_exists=False)
elif os.path.isfile('credentials.json'):
    with open('credentials.json') as f:
        credentials = json.load(f)
        print('Found local credentials')
        credentials_cos = credentials['credentials_cos']
        credentials_cloudant = credentials['credentials_cloudant']
        credentials_vr = credentials['credentials_vr']

        authenticator = IAMAuthenticator(credentials_vr["VR_API_KEY"])
        visual_recognition = VisualRecognitionV3(version="2018-03-19", authenticator=authenticator)
        visual_recognition.set_service_url(credentials_vr["VR_ENDPOINT"])
            
        client = Cloudant(credentials_cloudant["CLOUDANT_USER_NAME"], credentials_cloudant["CLOUDANT_PASSWORD"], url=credentials_cloudant["CLOUDANT_ENDPOINT"], connect=True)
        db = client[credentials_cloudant["DB_NAME"]]
        for doc in db:
            break
        cos = ibm_boto3.client(service_name='s3',
                                ibm_api_key_id=credentials_cos['COS_API_KEY_ID'],
                                ibm_service_instance_id=credentials_cos['COS_SERVICE_ID'],
                                config=Config(signature_version='oauth'),
                                ibm_auth_endpoint=credentials_cos['IBM_AUTH_ENDPOINT'],
                                endpoint_url=credentials_cos['COS_ENDPOINT'])

# On IBM Cloud Cloud Foundry, get the port number from the environment variable PORT
# When running this app on the local machine, default the port to 8000
port = int(os.getenv('PORT', 8000))

# @app.route('/')
# def root():
#     return app.send_static_file('index.html')

# /* Endpoint to greet and add a new visitor to database.
# * Send a POST request to localhost:8000/api/visitors with body
# * {
# *     "name": "Bob"
# * }
# */
@app.route('/api/imagesList', methods=['GET'])
def get_imageList():
    if db:
        docs = []
        query = Query(db, selector={'_id': {'$gt': 0}})
        i = 0
        max_iter = 8
        with query.custom_result() as rslt:
            start = random.randint(1,32)
            print(start)
            rslt = rslt[start:]
            for doc in rslt:
                if i <max_iter:
                    file_name = doc['file_name']
                    file_id = doc['_id']
                    bytes_buffer = io.BytesIO()
                    res = cos.download_fileobj(Bucket=credentials_cos['BUCKET'], Key=file_name, Fileobj=bytes_buffer)
                    byte_value = bytes_buffer.getvalue()
                    # str_value = byte_value.decode()
                    
                    # print( str_value)
                    base64_file =  base64.b64encode(byte_value)
                    base64_string = base64_file.decode(ENCODING)
                    data = { 'file_name' : file_name, 'file_id' : file_id, 'image_base64': base64_string}
                    if file_name.find("classification") != -1:
                        docs.append(data)
                        i = i + 1
                else:
                    break
        random.shuffle(docs)
        return jsonify(docs)
    else:
        print('No database')
        return jsonify([])

@app.route('/api/image', methods=['GET'])
def get_image():
    if db:
        return jsonify(list(map(lambda doc: doc['name'], db)))
    else:
        print('No database')
        return jsonify([])
# /**
#  * Endpoint to get a JSON array of all the visitors in the database
#  * REST API example:
#  * <code>
#  * GET http://localhost:8000/api/visitors
#  * </code>
#  *
#  * Response:
#  * [ "Bob", "Jane" ]
#  * @return An array of all the visitor names
#  */
@app.route('/api/guessClass', methods=['POST'])
def guessClass():
    file_id = request.json['file_id']
    answer = request.json['answer']
    data = {'file_id': file_id, 'answer': answer}
    if db:
        doc = db[file_id]
        answers = doc['answers']
        answers.append(answer)
        doc['answers'] = answers
        doc.save()
        return jsonify(doc)
    else:
        print('No database')
        return jsonify(data)

@app.route('/api/classify', methods=['POST'])
def classify():
    file_name = str(request.json['image_filename'])
    encoded_string = request.json['image_base64']
    base64_f = base64.b64decode(encoded_string)
    im = io.BytesIO(base64_f)
    if visual_recognition:
        classes = visual_recognition.classify(images_file=im, images_filename=file_name,classifier_ids=[credentials_vr["VR_MODEL"]]).get_result()
        data = {'file_name':file_name, 'answers': []}
        doc = db.create_document(data)
        im2 = io.BytesIO(base64_f)
        cos.upload_fileobj(im2,  credentials_cos['BUCKET'], file_name) 
        response = classes["images"][0]['classifiers'][0]["classes"][0]
        print(response)
        result = { 'score': response['score'], 'trash_class': response['class']}
        return jsonify(result)
    else:
        print('No model')
        return 
        # jsonify(data)
@atexit.register
def shutdown():
    if db:
        db.disconnect()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port, debug=True)