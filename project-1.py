from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import requests
import base64
import time
from typing import List, Optional
import json

app = FastAPI()

# Get environment variables
MY_SECRET = os.getenv("MY_SECRET")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_USERNAME = "SiriChandanaSykam"

class Attachment(BaseModel):
    name: str
    url: str

class TaskRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int
    nonce: str
    brief: str
    checks: List[str]
    evaluation_url: str
    attachments: Optional[List[Attachment]] = []

@app.post("/build")
async def receive_task(request: TaskRequest):
    """Main endpoint to receive task requests"""
    if request.secret != MY_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")
    
    try:
        print(f"Received task: {request.task}, round: {request.round}")
        
        print("Generating code with Groq...")
        html_code = generate_app_with_groq(request.brief, request.checks, request.attachments)
        
        repo_name = f"{request.task}"
        
        if request.round == 1:
            print(f"Creating GitHub repo: {repo_name}")
            repo_url, commit_sha = create_github_repo(repo_name, html_code, request.brief)
        else:
            print(f"Updating GitHub repo: {repo_name}")
            repo_url, commit_sha = update_github_repo(repo_name, html_code, request.brief)
        
        if request.round == 1:
            print("Enabling GitHub Pages...")
            enable_github_pages(repo_name)
        
        pages_url = f"https://{GITHUB_USERNAME}.github.io/{repo_name}/"
        
        print("Notifying evaluation URL...")
        notify_evaluation(request, repo_url, commit_sha, pages_url)
        
        print(f"Task completed successfully!")
        return {
            "status": "success",
            "repo_url": repo_url,
            "pages_url": pages_url,
            "commit_sha": commit_sha
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return {"status": "error", "message": str(e)}

def generate_app_with_groq(brief, checks, attachments):
    """Use Groq API to generate HTML code"""
    attachment_info = ""
    if attachments:
        attachment_info = "ATTACHMENTS:\n" + "\n".join([
            f"- {att.name}: {att.url[:100]}..." for att in attachments
        ])
    
    checks_list = "\n".join([f"- {check}" for check in checks])
    
    prompt = f"""Generate a complete single-page HTML application.

TASK BRIEF:
{brief}

REQUIREMENTS (the app MUST pass these checks):
{checks_list}

{attachment_info}

INSTRUCTIONS:
1. Create a COMPLETE, self-contained HTML file
2. Include ALL CSS in style tags within head
3. Include ALL JavaScript in script tags before body closing tag
4. Use Bootstrap 5 from CDN
5. Make sure ALL requirement checks will pass
6. Use professional, clean code

Return ONLY the HTML code, nothing else. No explanations."""

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are an expert web developer who creates complete, working HTML applications."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 8000
        }
    )
    
    html_code = response.json()["choices"][0]["message"]["content"]
    
    # Clean markdown code blocks
    backticks = chr(96) + chr(96) + chr(96)
    if backticks in html_code:
        parts = html_code.split(backticks)
        for part in parts:
            if "<html" in part.lower() or "<!DOCTYPE" in part.lower():
                html_code = part.replace("html", "").replace("HTML", "").strip()
                break
    
    return html_code

def create_github_repo(repo_name, html_code, brief):
    """Create repo, add files, return repo_url and commit_sha"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Create repository WITHOUT auto_init
    response = requests.post(
        "https://api.github.com/user/repos",
        headers=headers,
        json={
            "name": repo_name,
            "description": f"Auto-generated: {brief[:100]}",
            "private": False,
            "auto_init": False  # Changed from True to False
        }
    )
    
    if response.status_code != 201:
        raise Exception(f"Failed to create repo: {response.text}")
    
    repo_url = response.json()["html_url"]
    time.sleep(2)
    
    # Add README.md first (creates main branch)
    readme = generate_readme(repo_name, brief)
    add_file_to_repo(repo_name, "README.md", readme, "Initial commit", headers)
    
    time.sleep(1)
    
    # Add index.html
    commit_sha = add_file_to_repo(repo_name, "index.html", html_code, "Add generated app", headers)
    
    # Add LICENSE
    mit_license = get_mit_license()
    add_file_to_repo(repo_name, "LICENSE", mit_license, "Add MIT license", headers)
    
    return repo_url, commit_sha


def update_github_repo(repo_name, html_code, brief):
    """Update existing repo for round 2"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    repo_url = f"https://github.com/{GITHUB_USERNAME}/{repo_name}"
    
    commit_sha = update_file_in_repo(repo_name, "index.html", html_code, "Update app for round 2", headers)
    
    readme = generate_readme(repo_name, brief, round_num=2)
    update_file_in_repo(repo_name, "README.md", readme, "Update README for round 2", headers)
    
    return repo_url, commit_sha

def add_file_to_repo(repo_name, file_path, content, message, headers):
    """Add a file to the repo and return commit SHA"""
    encoded_content = base64.b64encode(content.encode()).decode()
    
    response = requests.put(
        f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo_name}/contents/{file_path}",
        headers=headers,
        json={
            "message": message,
            "content": encoded_content
        }
    )
    
    if response.status_code not in [201, 200]:
        raise Exception(f"Failed to add {file_path}: {response.text}")
    
    return response.json()["commit"]["sha"]

def update_file_in_repo(repo_name, file_path, content, message, headers):
    """Update an existing file in the repo"""
    get_response = requests.get(
        f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo_name}/contents/{file_path}",
        headers=headers
    )
    
    if get_response.status_code != 200:
        return add_file_to_repo(repo_name, file_path, content, message, headers)
    
    file_sha = get_response.json()["sha"]
    encoded_content = base64.b64encode(content.encode()).decode()
    
    response = requests.put(
        f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo_name}/contents/{file_path}",
        headers=headers,
        json={
            "message": message,
            "content": encoded_content,
            "sha": file_sha
        }
    )
    
    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to update {file_path}: {response.text}")
    
    return response.json()["commit"]["sha"]

def enable_github_pages(repo_name):
    """Enable GitHub Pages for the repo"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo_name}/pages",
        headers=headers,
        json={"source": {"branch": "main", "path": "/"}}
    )
    
    if response.status_code not in [201, 409]:
        print(f"Warning: GitHub Pages response: {response.status_code}")
    
    time.sleep(5)

def notify_evaluation(request, repo_url, commit_sha, pages_url):
    """Send repo details to evaluation URL with retry logic"""
    payload = {
        "email": request.email,
        "task": request.task,
        "round": request.round,
        "nonce": request.nonce,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "pages_url": pages_url
    }
    
    for delay in [0, 1, 2, 4, 8]:
        if delay > 0:
            time.sleep(delay)
        
        try:
            response = requests.post(
                request.evaluation_url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"Evaluation notified successfully")
                return
            else:
                print(f"Evaluation URL returned {response.status_code}, retrying...")
        except Exception as e:
            print(f"Failed to notify evaluation URL: {e}, retrying...")
    
    print("Warning: Failed to notify evaluation URL after all retries")

def get_mit_license():
    """Return MIT license text"""
    return """MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

def generate_readme(repo_name, brief, round_num=1):
    """Generate README.md content"""
    return f"""# {repo_name}

## Summary
Auto-generated application (Round {round_num}): {brief}

## Setup
No setup required. This is a static HTML page deployed on GitHub Pages.

## Usage
1. Visit the GitHub Pages URL for this repository
2. The application will load and run in your browser
3. Follow the on-screen instructions

## Code Explanation
This application was automatically generated using LLM-based code generation (Groq/Llama).

The code includes:
- Self-contained HTML with embedded CSS and JavaScript
- Bootstrap 5 for styling
- All required functionality as specified in the brief

## Deployment
- Hosted on GitHub Pages
- Automatically deployed from the main branch
- Updates are live within minutes of pushing changes

## License
MIT License - see LICENSE file for details"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
