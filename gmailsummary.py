# Install required components
# sudo pip3 install flask google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client openai requests

from flask import Flask, jsonify, request
import google.auth
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import googleapiclient.discovery
from googleapiclient.discovery import build
import openai
import os
import pickle
import logging
import requests
import base64
import configparser
import re

app = Flask(__name__)

# OpenAI API parameters
OPENAI_API_KEY = ""
CUSTOM_PROMPT = "Pretend to be a friendly assistant to someone that you know really well. Their name is Daniel, and they have just asked if there are any noteworthy new emails. Respond providing relevant summaries and if there are any important details or followups needed for each of the emails without just reading them out. Maybe slip in a joke if possible. Try to be observant of all the details in the data to come across as observant and emotionally intelligent as you can. Don't ask for a followup or if they need anything else. The emails are numbered below. Do not include the email numbers in your response. Don't include emojis in your response. Don't write fictional emails. If this is the last sentence of the prompt, simply tell the user that there were no emails to summarize right now."
OPENAI_ENGINE = "gpt-4"
OPENAI_MAX_TOKENS = 1000
OPENAI_TEMPERATURE = 0.7

# Set up OpenAI API credentials
openai.api_key = OPENAI_API_KEY

# Set up Google API credentials
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
creds = None
if os.path.exists('token.pickle'):
    with open('token.pickle', 'rb') as token:
        creds = pickle.load(token)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)

    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)

# Create a Gmail service instance
gmail_service = build('gmail', 'v1', credentials=creds)

# List that will store the latest fetched emails
latest_emails = []

def fetch_latest_emails():
    # Fetch a list of messages matching the query, and extract a list of messages from the results, or an empty list if none were found
    global latest_emails
    query = "is:unread -category:spam"
    results = gmail_service.users().messages().list(userId='me', q=query, maxResults=20).execute()   
    messages = results.get('messages', [])   

    # Initialize an empty list to store the latest emails
    latest_emails = []   

    # Fetch the full message details and extract label IDs and message headers
    for message in messages:   
        msg = gmail_service.users().messages().get(userId='me', id=message['id'], format='full').execute()   
        labels = msg.get("labelIds", [])
        headers = msg['payload']['headers']

        # Check if the message is unread, and extract the payload data and message parts
        if 'UNREAD' in labels:   
            payload = msg['payload']   
            parts = payload.get("parts")   

            # Extract the data from the first part, or the payload itself if there are no parts
            data = parts[0] if parts else payload   
            file_data = data.get("body", {}).get("data")   
            
            # Initializes an empty list to store the latest emails.
            if file_data:   
                file_data = file_data.replace("-", "+").replace("_", "/")   
                decoded_data = base64.b64decode(file_data)   
                if isinstance(decoded_data, bytes):   
                    decoded_data = decoded_data.decode("utf-8")   
           
            # If the message body is empty, set a default value
            else:
                decoded_data = "No content"   

            # Create a dictionary with email details
            mail_data = {   
                'id': msg['id'],
                'subject': next((header['value'] for header in headers if header['name'] == 'subject'), 'No Subject'),
                'from': next((header['value'] for header in headers if header['name'] == 'From'), 'Unknown Sender'),
                'body': decoded_data,
                'internalDate': int(msg['internalDate'])
            }
            
            # Add the email details to the latest emails list, stopping the loop if the maximum number of emails has been fetched
            latest_emails.append(mail_data)   
            if len(latest_emails) >= 10:
                break

    # Sort the emails by internal date (oldest first)
    sorted_emails = sorted(latest_emails, key=lambda email: email['internalDate'])

    # Update the latest_emails global variable
    latest_emails = sorted_emails
                
    # Print the latest_emails list to the terminal
    print("\n" + "#" * 45 + "\n    Latest Emails Fetched:   \n" + "#" * 45 + "\n")
    print(f"{latest_emails}")

@app.route('/fetch_emails', methods=['GET'])
def fetch_emails():
    fetch_latest_emails()
    return jsonify(latest_emails)

def mark_emails_unread(email_ids):
    # Marks a list of email IDs as unread using the Gmail API.
    service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

    for email_id in email_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            print(f"Marked email {email_id} as unread.")
        except Exception as e:
            print(f"An error occurred while marking email {email_id} as unread: {e}")

def remove_html_and_links(text):
    # Remove unwanted HTML code
    text = re.sub('<table.*?</table>', '', text, flags=re.DOTALL)
    
    # Remove HTML tags
    text = re.sub('<[^<]+?>', '', text)

    # Remove links
    text = re.sub(r'http\S+', '', text)

    # Remove CSS styles
    text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<\s*style[^>]*>[^<]*<\s*/\s*style\s*>', '', text, flags=re.DOTALL) # Added

    # Remove JavaScript code
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)

    # Remove comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # Remove consecutive whitespace characters
    text = re.sub('\s+', ' ', text)

    # Remove font code and Unicode code
    text = re.sub(r'(@font-face.*?;})', '', text, flags=re.DOTALL)
    text = re.sub(r'unicode-range:.*?;', '', text)

    # Remove unwanted code
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    # Remove blocks of code like &nbsp;&zwnj;&nbsp;&zwnj;...
    text = re.sub(r'(&\w+;)*[\u200b\u200c]*[\u00a0\u200b]*', '', text)

    # Remove code blocks
    text = re.sub(r'{[^{}]*}', '', text, flags=re.DOTALL)

    return text.strip()

@app.route('/get_emails_summary', methods=['POST'])
def get_emails_summary():
    # Fetch the latest emails
    fetch_latest_emails()

    # Get the list of email IDs from the request
    email_ids_string = request.form.get('ids')

    # Split the email IDs string into a list of email IDs
    email_ids = email_ids_string.replace('ids[]=', '').strip('"').split('","')

    # Print the received email IDs
    print(f"Received email IDs: {email_ids}")

    # Find the emails with the given ids in the latest_emails list
    emails = [e for e in latest_emails if e['id'] in email_ids and e.get('subject', '') != 'No subject' and e.get('content', '') != 'No content']

    # Concatenate the email content
    email_content = ""
    for i, email in enumerate(emails):
        email_content += f"Email {i + 1}:\nSubject: {email['subject']}\nFrom: {email['from']}\n\n{email['body']}\n\n"

    # Remove HTML and links from email content
    email_content = remove_html_and_links(email_content)

    # Generate the prompt for the emails
    prompt = f"{CUSTOM_PROMPT}\n\n{email_content}"

    # Print the prompt to the console
    print("\n" + "#" * 45 + "\n    Generated Prompt:   \n" + "#" * 45 + "\n")
    print(prompt)

    # Generate a summary of the emails using the OpenAI API
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    data = {
        "model": OPENAI_ENGINE,
        "messages": [
            {"role": "system", "content": prompt},
        ],
        "max_tokens": OPENAI_MAX_TOKENS,
        "n": 1,
        "temperature": OPENAI_TEMPERATURE,
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=data,
    )

    response_json = response.json()
    print("\n" + "#" * 45 + "\n    OpenAI Response Payload:   \n" + "#" * 45 + "\n")
    print(response_json)

    if 'error' in response_json:
        print(f"Error: {response_json['error']['message']}")
        return jsonify({"error": response_json["error"]["message"]})

    summary = response_json["choices"][0]["message"]["content"].strip()
    
    # Mark the emails as unread
    print("\n" + "#" * 45 + "\n    Marking emails as unread.   \n" + "#" * 45 + "\n")
    mark_emails_unread(email_ids)

    # Return the summary as plain text instead of JSON
    print("\n" + "#" * 45 + "\n    OpenAI Response:   \n" + "#" * 45 + "\n")
    print(summary)
    return summary

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=1337)
