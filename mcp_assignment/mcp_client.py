#!/usr/bin/env python3
"""
Complete MCP Implementation GitHub API and File System
Uses Docker-based GitHub MCP Server
"""

import asyncio
import os
import json
import httpx
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import base64
from mcp_docker_client import MCPDockerClient


PERSONAS = {
    "eng01": {
        "name": "Alex Chen",
        "team": "Engineering",
        "persona": "Software Engineer",
        "location": "US",
        "permissions": {
            "github": "read_write",
            "filesystem": ["Engineering"]
        }
    },
    "it01": {
        "name": "Priya Nair",
        "team": "IT",
        "persona": "ITSM Analyst",
        "location": "Germany",
        "permissions": {
            "github": "read_only",
            "filesystem": ["IT"]
        }
    },
    "sales01": {
        "name": "Marco Diaz",
        "team": "Sales",
        "persona": "Account Executive",
        "location": "India",
        "permissions": {
            "github": "none",
            "filesystem": ["Sales"]
        }
    }
}

TASK_MAPPING = {
    "feature": "Feature Development",
    "development": "Feature Development",
    "bug": "Production Support",
    "fix": "Production Support",
    "support": "Production Support",
    "incident": "Incident/Ticket Resolution",
    "ticket": "Incident/Ticket Resolution",
    "infrastructure": "Infrastructure Maintenance",
    "maintenance": "Infrastructure Maintenance",
    "lead": "Lead Generation",
    "proposal": "Proposal Development",
    "campaign": "Lead Generation"
}

TASK_TO_PERSONA = {
    "Feature Development": "eng01",
    "Production Support": "eng01",
    "Incident/Ticket Resolution": "it01",
    "Infrastructure Maintenance": "it01",
    "Lead Generation": "sales01",
    "Proposal Development": "sales01"
}

BASE_DIR = Path(__file__).parent / "persona_data"

class RealMCPClient:
    def __init__(self, user_id: str = "eng01", use_mcp_docker: bool = True):
        """Initialize MCP client with GitHub and FileSystem access
        
        Args:
            user_id: Persona user ID
            use_mcp_docker: If True, use Docker-based MCP server; if False, use direct API calls
        """
        self.user_id = user_id
        self.persona = PERSONAS.get(user_id)
        if not self.persona:
            raise ValueError(f"Unknown user_id: {user_id}")
        
        self.use_mcp_docker = use_mcp_docker
        
        # GitHub setup - Use MCP Docker server or direct API
        self.github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")
        self.github_base_url = "https://api.github.com"
        
        # MCP Docker client setup
        self.mcp_client = None
        if self.use_mcp_docker:
            # Determine if read-only based on persona permissions
            read_only = self.persona["permissions"]["github"] == "read_only"
            self.mcp_client = MCPDockerClient(
                github_token=self.github_token,
                read_only=read_only
            )
            print("[INFO] Using Docker-based GitHub MCP Server")
        else:
            if not self.github_token:
                print("[WARNING] No GITHUB_TOKEN found in environment. Set it for real GitHub access:")
                print("          export GITHUB_TOKEN='your_github_token'")
                print("          or create a .env file with: GITHUB_TOKEN=your_token")
        
        # FileSystem setup
        self._init_persona_directories()
        
        # Database setup - for ticket tracking
        self._init_database()
        
        print(f"[INFO] MCP Client initialized for {self.persona['name']}")
        print(f"[INFO] GitHub Access: {self.persona['permissions']['github']}")
        print(f"[INFO] FileSystem Access: {', '.join(self.persona['permissions']['filesystem'])}")
    
    async def _ensure_mcp_connected(self):
        """Ensure MCP Docker client is started and connected"""
        if self.use_mcp_docker and self.mcp_client:
            if not self.mcp_client.initialized:
                await self.mcp_client.start()
    
    async def cleanup(self):
        """Cleanup MCP client connection"""
        if self.use_mcp_docker and self.mcp_client:
            await self.mcp_client.stop()
    
    def _init_persona_directories(self):
        """Initialize REAL persona-specific directories"""
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        
        for folder in self.persona["permissions"]["filesystem"]:
            folder_path = BASE_DIR / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            print(f"[INFO] FileSystem folder ready: {folder_path}")
            
            # Create initial sample files if empty
            if not any(folder_path.iterdir()):
                self._create_sample_files(folder_path, folder)
    
    def _create_sample_files(self, folder_path: Path, folder_name: str):
        """Create sample files for demonstration"""
        if folder_name == "Engineering":
            (folder_path / "README.md").write_text(
                "# Engineering Workspace\n\nThis folder contains engineering documents and code."
            )
            (folder_path / "design_doc.md").write_text(
                "# Feature Design Document\n\n## Overview\nSample design document for new features."
            )
        elif folder_name == "IT":
            (folder_path / "incident_log.txt").write_text(
                "Incident Log\n============\n[2025-01-15] Server outage resolved\n[2025-01-14] Database connection timeout"
            )
            (folder_path / "maintenance_script.sh").write_text(
                "#!/bin/bash\n# Infrastructure maintenance script\necho 'Running maintenance...'"
            )
        elif folder_name == "Sales":
            (folder_path / "proposal_template.md").write_text(
                "# Sales Proposal Template\n\n## Client Information\n## Proposed Solution\n## Pricing"
            )
            (folder_path / "leads.csv").write_text(
                "Name,Email,Company,Status\nJohn Doe,john@example.com,Acme Corp,Qualified\nJane Smith,jane@example.com,Tech Inc,New"
            )
        
        print(f"[INFO] Created sample files in {folder_path}")
    
    def _init_database(self):
        """Initialize SQLite database for ticket tracking"""
        db_path = BASE_DIR / "tickets.db"
        self.db_path = db_path
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create tickets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'Open',
                persona_id TEXT NOT NULL,
                persona_name TEXT NOT NULL,
                team TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                priority TEXT DEFAULT 'Medium',
                category TEXT
            )
        """)
        
        # Create ticket_updates table for tracking changes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                update_text TEXT,
                updated_by TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            )
        """)
        
        conn.commit()
        conn.close()
        print(f"[INFO] Database initialized: {db_path}")
    
    def map_prompt_to_task(self, prompt: str) -> str:
        """Map prompt to task using keyword matching"""
        prompt_lower = prompt.lower()
        for keyword, task in TASK_MAPPING.items():
            if keyword in prompt_lower:
                return task
        return "Unknown Task"
    
    def get_persona_for_task(self, task: str) -> Optional[str]:
        """Get persona (user_id) for a given task"""
        return TASK_TO_PERSONA.get(task)
    
    def check_permission(self, resource: str, action: str) -> bool:
        """Check if user has permission for resource and action"""
        permissions = self.persona["permissions"]
        
        if resource == "github":
            github_perm = permissions.get("github", "none")
            if action == "read":
                return github_perm in ["read_only", "read_write"]
            elif action == "write":
                return github_perm == "read_write"
            return False
        
        elif resource == "filesystem":
            if action in ["read", "write"]:
                return len(permissions.get("filesystem", [])) > 0
            return False
        
        return False
    
    async def github_list_repos(self, username: str = None) -> Dict[str, Any]:
        """List GitHub repositories - Uses MCP Docker server or direct API"""
        if not self.check_permission("github", "read"):
            raise PermissionError(f"User {self.user_id} does not have GitHub read permission")
        
        # Use MCP Docker server if enabled
        if self.use_mcp_docker:
            await self._ensure_mcp_connected()
            print(f"[MCP] Calling GitHub MCP tool: search_repositories")
            result = await self.mcp_client.list_repositories(username=username, per_page=100)
            
            # Transform MCP result to match expected format
            # The search_repositories tool returns items
            repos = result.get("items", result.get("repositories", []))
            print(f"[MCP] Found {len(repos)} repositories in search result")
            
            return {
                "count": len(repos),
                "repositories": [
                    {
                        "name": r.get("name", ""),
                        "full_name": r.get("fullName", r.get("full_name", r.get("fullName", ""))),
                        "private": r.get("private", False),
                        "description": r.get("description", ""),
                        "url": r.get("url", r.get("htmlUrl", r.get("html_url", "")))
                    }
                    for r in repos
                ]
            }
        
        # Fallback to direct API call
        if not self.github_token:
            raise ConnectionError("GitHub token not configured. Set GITHUB_TOKEN environment variable.")
        
        # Use authenticated user's repos if no username
        url = f"{self.github_base_url}/user/repos?sort=updated&per_page=10"
        if username:
            url = f"{self.github_base_url}/users/{username}/repos?sort=updated&per_page=10"
        
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        print(f"[API] Calling GitHub API: GET {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            repos = response.json()
            
            return {
                "count": len(repos),
                "repositories": [
                    {
                        "name": r["name"],
                        "full_name": r["full_name"],
                        "private": r["private"],
                        "description": r.get("description", ""),
                        "url": r["html_url"]
                    }
                    for r in repos
                ]
            }
    
    async def github_get_file(self, owner: str, repo: str, path: str) -> Dict[str, Any]:
        """Get file content from GitHub - Uses MCP Docker server or direct API"""
        if not self.check_permission("github", "read"):
            raise PermissionError(f"User {self.user_id} does not have GitHub read permission")
        
        # Use MCP Docker server if enabled
        if self.use_mcp_docker:
            await self._ensure_mcp_connected()
            print(f"[MCP] Calling GitHub MCP tool: get_file_contents")
            result = await self.mcp_client.get_file(owner, repo, path)
            
            # Debug: print the actual result structure
            print(f"[MCP DEBUG] get_file result type: {type(result)}")
            if isinstance(result, dict):
                print(f"[MCP DEBUG] get_file result keys: {list(result.keys())}")
                print(f"[MCP DEBUG] get_file result sample: {str(result)[:500]}")
            
            # Transform MCP result to match expected format
            # The get_file_contents tool returns data in content format
            content = ""
            file_sha = ""
            file_name = ""
            file_url = ""
            file_size = 0
            
            # Handle both dict and list responses
            content_list = []
            if isinstance(result, dict):
                # Check if result is in content format (like get_me)
                if "content" in result:
                    content_list = result.get("content", [])
                else:
                    content_list = [result]
            elif isinstance(result, list):
                # Result is a list
                content_list = result
            
            print(f"[MCP DEBUG] content_list length: {len(content_list)}")
            # First pass: extract SHA from text items
            for idx, item in enumerate(content_list):
                print(f"[MCP DEBUG] content_list[{idx}] type: {type(item)}, keys: {list(item.keys()) if isinstance(item, dict) else 'N/A'}")
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    print(f"[MCP DEBUG] text item: {text[:100]}")
                    # Extract SHA from text like "successfully downloaded text file (SHA: ...)"
                    import re
                    sha_match = re.search(r'SHA:\s*([a-f0-9]+)', text)
                    if sha_match:
                        file_sha = sha_match.group(1)
                        print(f"[MCP DEBUG] Extracted SHA from text: {file_sha}")
            
            # Extract content from resource items
            for idx, item in enumerate(content_list):
                if isinstance(item, dict) and item.get("type") == "resource":
                    resource = item.get("resource", {})
                    print(f"[MCP DEBUG] resource keys: {list(resource.keys()) if resource else 'N/A'}")
                    if resource:
                        content = resource.get("text", resource.get("content", ""))
                        # Only set SHA from resource if not already set from text
                        if not file_sha:
                            file_sha = resource.get("sha", "")
                        file_url = resource.get("uri", "")
                        print(f"[MCP DEBUG] Extracted from resource: content_len={len(content)}, sha={file_sha[:20] if file_sha else 'None'}")
            
            # Also try direct access
            if isinstance(result, dict):
                if not content:
                    content = result.get("content", result.get("text", ""))
                if not file_sha:
                    file_sha = result.get("sha", "")
                if not file_name:
                    file_name = result.get("name", "")
                if not file_url:
                    file_url = result.get("url", result.get("htmlUrl", result.get("uri", "")))
                if not file_size:
                    file_size = result.get("size", len(content) if content else 0)
            
            print(f"[MCP DEBUG] Final extracted values: sha={file_sha[:20] if file_sha else 'None'}, content_len={len(content)}")
            
            # Get path and name from result if it is a dict
            result_path = path
            result_name = file_name
            if isinstance(result, dict):
                result_path = result.get("path", path)
                result_name = file_name or result.get("name", "")
            
            return {
                "name": result_name,
                "path": result_path,
                "size": file_size,
                "content": content,
                "url": file_url,
                "sha": file_sha
            }
        
        # Fallback to direct API call
        if not self.github_token:
            raise ConnectionError("GitHub token not configured")
        
        url = f"{self.github_base_url}/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        print(f"[API] Calling GitHub API: GET {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            # Decode base64 content
            content = ""
            if data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8")
            
            return {
                "name": data["name"],
                "path": data["path"],
                "size": data["size"],
                "content": content,
                "url": data["html_url"],
                "sha": data.get("sha")  # Include SHA for updates
            }
    
    async def github_create_file(self, owner: str, repo: str, path: str, 
                                 content: str, message: str) -> Dict[str, Any]:
        """Create file in GitHub - Uses MCP Docker server or direct API"""
        if not self.check_permission("github", "write"):
            raise PermissionError(f"User {self.user_id} does not have GitHub write permission")
        
        # Use MCP Docker server if enabled
        if self.use_mcp_docker:
            await self._ensure_mcp_connected()
            print(f"[MCP] Calling GitHub MCP tool: create_or_update_file")
            # Default to "main" branch if not specified
            result = await self.mcp_client.create_file(owner, repo, path, content, message, branch="main")
            
            # Debug: print the actual result structure
            print(f"[MCP DEBUG] create_file result type: {type(result)}")
            if isinstance(result, dict):
                print(f"[MCP DEBUG] create_file result keys: {list(result.keys())}")
                
                # Check for errors first
                if result.get("isError", False):
                    error_text = ""
                    if "content" in result:
                        content_list = result.get("content", [])
                        if content_list and isinstance(content_list[0], dict):
                            error_text = content_list[0].get("text", "Unknown error")
                    raise RuntimeError(f"Failed to create file: {error_text}")
                
                print(f"[MCP DEBUG] create_file result sample: {str(result)[:500]}")
            
            # Transform MCP result to match expected format
            # The create_or_update_file tool returns data in different formats
            if isinstance(result, dict):
                # Check if result is in content format
                if "content" in result and not result.get("isError", False):
                    content_list = result.get("content", [])
                    if content_list and isinstance(content_list[0], dict):
                        text_content = content_list[0].get("text", "")
                        if text_content:
                            try:
                                import json
                                parsed = json.loads(text_content)
                                print(f"[MCP DEBUG] Parsed content type: {type(parsed)}")
                                if isinstance(parsed, dict):
                                    result = parsed
                                    print(f"[MCP DEBUG] Parsed result keys: {list(result.keys())}")
                            except Exception as e:
                                print(f"[MCP DEBUG] Failed to parse content: {e}")
                
                # Extract data from result
                file_path = path
                file_sha = ""
                file_url = ""
                
                # Extract the data
                if "content" in result:
                    content_obj = result.get("content", {})
                    if isinstance(content_obj, dict):
                        file_path = content_obj.get("path", content_obj.get("name", path))
                        file_sha = content_obj.get("sha", "")
                        file_url = content_obj.get("htmlUrl", content_obj.get("html_url", content_obj.get("url", "")))
                
                # Direct access
                if not file_path or file_path == path:
                    file_path = result.get("path", result.get("name", path))
                if not file_sha:
                    file_sha = result.get("sha", "")
                if not file_url:
                    file_url = result.get("url", result.get("htmlUrl", result.get("html_url", "")))
                
                return {
                    "path": file_path,
                    "sha": file_sha,
                    "url": file_url,
                    "message": "File created successfully"
                }
            else:
                # If result is not a dict, return with path info
                print(f"[MCP WARNING] Unexpected result type: {type(result)}")
                return {
                    "path": path,
                    "sha": "",
                    "url": "",
                    "message": "File created successfully",
                    "raw_result": str(result)[:200]
                }
        
        # Fallback to direct API call
        if not self.github_token:
            raise ConnectionError("GitHub token not configured")
        
        url = f"{self.github_base_url}/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Encode content to base64
        content_b64 = base64.b64encode(content.encode()).decode()
        
        data = {
            "message": message,
            "content": content_b64
        }
        
        print(f"[API] Calling GitHub API: PUT {url}")
        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=headers, json=data, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            
            return {
                "path": result["content"]["path"],
                "sha": result["content"]["sha"],
                "url": result["content"]["html_url"],
                "message": "File created successfully"
            }
    
    async def github_update_file(self, owner: str, repo: str, path: str, 
                                 content: str, message: str) -> Dict[str, Any]:
        """Update existing file in GitHub - Uses MCP Docker server or direct API"""
        if not self.check_permission("github", "write"):
            raise PermissionError(f"User {self.user_id} does not have GitHub write permission")
        
        # Use MCP Docker server if enabled
        if self.use_mcp_docker:
            await self._ensure_mcp_connected()
            print(f"[MCP] Calling GitHub MCP tool: update_file")
            
            # Get the file to get its SHA
            try:
                file_data = await self.github_get_file(owner, repo, path)
                file_sha = file_data.get("sha", "")
                print(f"[MCP DEBUG] Got file SHA: {file_sha}")
            except Exception as e:
                print(f"[MCP DEBUG] Failed to get file SHA: {e}")
                file_sha = None
            
            try:
                result = await self.mcp_client.update_file(owner, repo, path, content, message, branch="main", sha=file_sha)

                # Print the actual result structure
                print(f"[MCP DEBUG] update_file result type: {type(result)}")
                if isinstance(result, dict):
                    print(f"[MCP DEBUG] update_file result keys: {list(result.keys())}")
                    
                    # Check for errors
                    if result.get("isError", False):
                        error_text = ""
                        if "content" in result:
                            content_list = result.get("content", [])
                            if content_list and isinstance(content_list[0], dict):
                                error_text = content_list[0].get("text", "Unknown error")
                        raise RuntimeError(f"Failed to update file: {error_text}")
                    
                    print(f"[MCP DEBUG] update_file result sample: {str(result)[:500]}")
                
                # Transform MCP result to match expected format
                file_path = path
                file_sha = ""
                file_url = ""
                
                if isinstance(result, dict):
                    # Check if result is in content format
                    if "content" in result and not result.get("isError", False):
                        content_list = result.get("content", [])
                        for item in content_list:
                            if isinstance(item, dict) and item.get("type") == "resource":
                                resource = item.get("resource", {})
                                if resource:
                                    file_path = resource.get("path", path)
                                    file_sha = resource.get("sha", "")
                                    file_url = resource.get("uri", "")
                    
                    # Also try direct access
                    if not file_path or file_path == path:
                        file_path = result.get("path", result.get("name", path))
                    if not file_sha:
                        file_sha = result.get("sha", "")
                    if not file_url:
                        file_url = result.get("url", result.get("htmlUrl", result.get("html_url", "")))
                
                return {
                    "path": file_path,
                    "sha": file_sha,
                    "url": file_url,
                    "message": "File updated successfully"
                }
            except Exception as e:
                # If update fails, create the file
                if "not found" in str(e).lower() or "404" in str(e) or "missing" in str(e).lower():
                    print("[INFO] File not found or update failed, creating new file...")
                    return await self.github_create_file(owner, repo, path, content, message)
                raise
        
        # Fallback to direct API call
        if not self.github_token:
            raise ConnectionError("GitHub token not configured")
        
        # Get the file to get its SHA
        url = f"{self.github_base_url}/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        print(f"[API] Calling GitHub API: GET {url} (to get SHA)")
        async with httpx.AsyncClient() as client:
            # Get existing file to retrieve SHA
            get_response = await client.get(url, headers=headers, timeout=10.0)
            
            if get_response.status_code == 404:
                # File doesn't exist, create it
                print("[INFO] File not found, creating new file...")
                return await self.github_create_file(owner, repo, path, content, message)
            
            get_response.raise_for_status()
            file_data = get_response.json()
            sha = file_data.get("sha")
            
            if not sha:
                raise ValueError("Could not retrieve SHA for file update")
            
            # Base64 encode content
            content_b64 = base64.b64encode(content.encode()).decode()
            
            data = {
                "message": message,
                "content": content_b64,
                "sha": sha  # Required for update
            }
            
            print(f"[API] Calling GitHub API: PUT {url} (UPDATE)")
            response = await client.put(url, headers=headers, json=data, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            
            return {
                "path": result["content"]["path"],
                "sha": result["content"]["sha"],
                "url": result["content"]["html_url"],
                "message": "File updated successfully"
            }
    
    def filesystem_list_files(self, folder: str = None) -> Dict[str, Any]:
        """List files in persona folder"""
        if not self.check_permission("filesystem", "read"):
            raise PermissionError(f"User {self.user_id} does not have filesystem read permission")
        
        allowed_folders = self.persona["permissions"]["filesystem"]
        if folder and folder not in allowed_folders:
            raise PermissionError(f"User {self.user_id} cannot access folder: {folder}")
        
        if not folder:
            folder = allowed_folders[0]
        
        folder_path = BASE_DIR / folder
        print(f"[FS] Listing files in: {folder_path}")
        
        files = []
        for item in folder_path.iterdir():
            stat = item.stat()
            files.append({
                "name": item.name,
                "type": "file" if item.is_file() else "directory",
                "size": stat.st_size if item.is_file() else 0,
                "path": str(item.relative_to(BASE_DIR))
            })
        
        return {
            "folder": folder,
            "path": str(folder_path),
            "count": len(files),
            "files": files
        }
    
    def filesystem_read_file(self, folder: str, filename: str) -> Dict[str, Any]:
        """Read file from persona folder"""
        if not self.check_permission("filesystem", "read"):
            raise PermissionError(f"User {self.user_id} does not have filesystem read permission")
        
        allowed_folders = self.persona["permissions"]["filesystem"]
        if folder not in allowed_folders:
            raise PermissionError(f"User {self.user_id} cannot access folder: {folder}")
        
        file_path = BASE_DIR / folder / filename
        print(f"[FS] Reading file: {file_path}")
        
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"File not found: {filename}")
        
        content = file_path.read_text()
        stat = file_path.stat()
        
        return {
            "filename": filename,
            "folder": folder,
            "path": str(file_path),
            "size": stat.st_size,
            "content": content
        }
    
    def filesystem_write_file(self, folder: str, filename: str, content: str) -> Dict[str, Any]:
        """Write file to persona folder"""
        if not self.check_permission("filesystem", "write"):
            raise PermissionError(f"User {self.user_id} does not have filesystem write permission")
        
        allowed_folders = self.persona["permissions"]["filesystem"]
        if folder not in allowed_folders:
            raise PermissionError(f"User {self.user_id} cannot access folder: {folder}")
        
        file_path = BASE_DIR / folder / filename
        existed = file_path.exists()
        
        print(f"[FS] Writing file: {file_path}")
        file_path.write_text(content)
        
        stat = file_path.stat()
        
        return {
            "filename": filename,
            "folder": folder,
            "path": str(file_path),
            "size": stat.st_size,
            "status": "updated" if existed else "created"
        }
    
    # ========================================================================
    # Ticket Database Operations
    # ========================================================================
    
    def create_ticket(self, title: str, description: str, priority: str = "Medium", category: str = None) -> Dict[str, Any]:
        """Create a new ticket in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Generate unique ticket ID
        ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self.user_id}"
        
        try:
            cursor.execute("""
                INSERT INTO tickets (ticket_id, title, description, status, persona_id, persona_name, team, priority, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticket_id, title, description, "Open", self.user_id, self.persona['name'], 
                  self.persona['team'], priority, category))
            
            # Add initial update
            cursor.execute("""
                INSERT INTO ticket_updates (ticket_id, update_text, updated_by)
                VALUES (?, ?, ?)
            """, (ticket_id, f"Ticket created: {title}", self.persona['name']))
            
            conn.commit()
            
            # Get the created ticket
            cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
            row = cursor.fetchone()
            ticket = self._row_to_ticket_dict(cursor, row)
            
            return ticket
        finally:
            conn.close()
    
    def get_ticket(self, ticket_id: str = None) -> Dict[str, Any]:
        """Get a ticket by ID or get the most recent ticket"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if ticket_id:
                # Debug: print the ticket_id being queried
                print(f"[DEBUG] get_ticket: Querying for ticket_id: '{ticket_id}'")
                cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
            else:
                # Get most recent ticket
                # IT can see all tickets, others see only their own
                print(f"[DEBUG] get_ticket: No ticket_id provided, getting most recent ticket for {self.user_id}")
                if self.user_id == "it01":
                    cursor.execute("""
                        SELECT * FROM tickets 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """)
                else:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE persona_id = ? 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """, (self.user_id,))
            
            row = cursor.fetchone()
            if row:
                ticket = self._row_to_ticket_dict(cursor, row)
                print(f"[DEBUG] get_ticket: Found ticket: {ticket['ticket_id']}")
                
                # Get updates for this ticket
                cursor.execute("""
                    SELECT update_text, updated_by, updated_at 
                    FROM ticket_updates 
                    WHERE ticket_id = ? 
                    ORDER BY updated_at
                """, (ticket['ticket_id'],))
                updates = [{"text": r[0], "by": r[1], "at": r[2]} for r in cursor.fetchall()]
                ticket['updates'] = updates
                
                return ticket
            return None
        finally:
            conn.close()
    
    def list_tickets(self, status: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """List tickets, optionally filtered by status"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # IT persona can see all tickets
            # Other personas see only their own tickets
            if self.user_id == "it01":
                # IT can see all tickets
                if status:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE status = ?
                        ORDER BY created_at DESC 
                        LIMIT ?
                    """, (status, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        ORDER BY created_at DESC 
                        LIMIT ?
                    """, (limit,))
            else:
                # Other personas see only their own tickets
                if status:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE persona_id = ? AND status = ?
                        ORDER BY created_at DESC 
                        LIMIT ?
                    """, (self.user_id, status, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE persona_id = ?
                        ORDER BY created_at DESC 
                        LIMIT ?
                    """, (self.user_id, limit))
            
            tickets = []
            for row in cursor.fetchall():
                tickets.append(self._row_to_ticket_dict(cursor, row))
            
            return tickets
        finally:
            conn.close()
    
    def update_ticket(self, ticket_id: str, update_text: str = None, status: str = None, 
                      priority: str = None, category: str = None) -> Dict[str, Any]:
        """Update a ticket - IT can update any ticket, others can only update their own"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if ticket exists and user has permission
            cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
            ticket_row = cursor.fetchone()
            if not ticket_row:
                raise ValueError(f"Ticket not found: {ticket_id}")
            
            ticket_data = self._row_to_ticket_dict(cursor, ticket_row)
            
            # Check permissions: IT can update any ticket, others can only update their own
            if self.user_id != "it01" and ticket_data['persona_id'] != self.user_id:
                raise PermissionError(f"User {self.user_id} cannot update ticket created by {ticket_data['persona_id']}")
            
            # Build update query dynamically
            updates = []
            params = []
            
            if status:
                updates.append("status = ?")
                params.append(status)
                if status in ["Resolved", "Closed"]:
                    updates.append("resolved_at = CURRENT_TIMESTAMP")
            
            if priority:
                updates.append("priority = ?")
                params.append(priority)
            
            if category:
                updates.append("category = ?")
                params.append(category)
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(ticket_id)
            
            if updates:
                query = f"UPDATE tickets SET {', '.join(updates)} WHERE ticket_id = ?"
                cursor.execute(query, params)
            
            # Add update entry
            if update_text:
                cursor.execute("""
                    INSERT INTO ticket_updates (ticket_id, update_text, updated_by)
                    VALUES (?, ?, ?)
                """, (ticket_id, update_text, self.persona['name']))
            elif status:
                cursor.execute("""
                    INSERT INTO ticket_updates (ticket_id, update_text, updated_by)
                    VALUES (?, ?, ?)
                """, (ticket_id, f"Status changed to: {status}", self.persona['name']))
            
            conn.commit()
            
            # Get updated ticket
            cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row:
                ticket = self._row_to_ticket_dict(cursor, row)
                
                # Get updates
                cursor.execute("""
                    SELECT update_text, updated_by, updated_at 
                    FROM ticket_updates 
                    WHERE ticket_id = ? 
                    ORDER BY updated_at
                """, (ticket_id,))
                updates = [{"text": r[0], "by": r[1], "at": r[2]} for r in cursor.fetchall()]
                ticket['updates'] = updates
                
                return ticket
            return None
        finally:
            conn.close()
    
    def _row_to_ticket_dict(self, cursor, row) -> Dict[str, Any]:
        """Convert database row to dictionary"""
        if not row:
            return None
        
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
