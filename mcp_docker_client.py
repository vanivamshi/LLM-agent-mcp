#!/usr/bin/env python3
"""
MCP Client for Docker-based GitHub MCP Server
Communicates with GitHub MCP server via stdio using JSON-RPC protocol
"""

import asyncio
import json
import os
import subprocess
from typing import Dict, Any, Optional, List
import uuid


class MCPDockerClient:
    """Client for communicating with GitHub MCP server via Docker stdio"""
    
    def __init__(self, github_token: Optional[str] = None, read_only: bool = False):
        """
        Initialize MCP Docker client
        
        Args:
            github_token: GitHub Personal Access Token (or use GITHUB_PERSONAL_ACCESS_TOKEN env var)
            read_only: Run server in read-only mode
        """
        self.github_token = github_token or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")
        self.read_only = read_only
        self.process = None
        self.request_id = 0
        self.initialized = False
        self.tools = {}
        self.resources = {}
        
    async def start(self):
        """Start the Docker container and initialize MCP connection"""
        if not self.github_token:
            raise ValueError("GitHub token required. Set GITHUB_PERSONAL_ACCESS_TOKEN or GITHUB_TOKEN environment variable")
        
        # Check if Docker is available
        use_sudo = False
        try:
            check_process = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await check_process.wait()
            if check_process.returncode != 0:
                # Try with sudo
                sudo_check = await asyncio.create_subprocess_exec(
                    "sudo", "docker", "version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await sudo_check.wait()
                if sudo_check.returncode == 0:
                    use_sudo = True
                    print("[MCP] Docker requires sudo privileges")
                else:
                    raise RuntimeError("Docker is not available. Make sure Docker is installed and running.")
        except FileNotFoundError:
            raise RuntimeError("Docker command not found. Make sure Docker is installed.")
        
        # Build Docker command
        docker_cmd = []
        if use_sudo:
            docker_cmd.append("sudo")
        docker_cmd.extend([
            "docker", "run", "-i", "--rm",
            "-e", f"GITHUB_PERSONAL_ACCESS_TOKEN={self.github_token}"
        ])
        
        if self.read_only:
            docker_cmd.extend(["-e", "GITHUB_READ_ONLY=1"])
        
        docker_cmd.append("ghcr.io/github/github-mcp-server")
        docker_cmd.append("stdio")
        
        print(f"[MCP] Starting Docker container: {' '.join(docker_cmd[:4])} ... {docker_cmd[-2]}")
        
        # Start Docker container
        try:
            self.process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start Docker container: {e}. Make sure Docker is running and the image is available.")
        
        # Initialize MCP connection
        await self._initialize()
        
    async def _initialize(self):
        """Initialize MCP protocol handshake"""
        # Wait for Docker container to start
        await asyncio.sleep(0.5)
        
        # Check if process already exited
        if self.process.returncode is not None:
            # Process exited
            try:
                stderr_output = await asyncio.wait_for(
                    self.process.stderr.read(),
                    timeout=1.0
                )
                if stderr_output:
                    error_msg = stderr_output.decode().strip()
                    raise ConnectionError(f"Docker container exited immediately: {error_msg}")
            except asyncio.TimeoutError:
                pass
            raise ConnectionError("Docker container exited immediately")
        
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "clientInfo": {
                    "name": "mcp-python-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print(f"MCP Sending initialize request...")
        response = await self._send_request(init_request)
        
        if not response:
            # Check if process is still running
            if self.process.returncode is not None:
                # Process exited, read stderr for error
                stderr_output = await self.process.stderr.read()
                if stderr_output:
                    error_msg = stderr_output.decode().strip()
                    raise ConnectionError(f"Docker container exited with error: {error_msg}")
                raise ConnectionError("Docker container exited unexpectedly")
            raise ConnectionError("No response from MCP server. Check Docker is running and image is available.")
        
        if "error" in response:
            error = response["error"]
            raise ConnectionError(f"MCP Initialization error: {error.get('message', 'Unknown error')} (code: {error.get('code', 'unknown')})")

        if response and "result" in response:
            # Store server info and capabilities
            self.server_info = response["result"].get("serverInfo", {})
            self.capabilities = response["result"].get("capabilities", {})
            
            # Send initialized notification
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            await self._send_notification(initialized_notification)
            
            # List available tools
            await self._list_tools()
            
            self.initialized = True
            print(f"[MCP] Connected to GitHub MCP Server: {self.server_info.get('name', 'unknown')} v{self.server_info.get('version', 'unknown')}")
            print(f"[MCP] Available tools: {len(self.tools)}")
            if len(self.tools) > 0:
                # Show first few tool names for debugging
                tool_names = list(self.tools.keys())[:5]
                print(f"[MCP] Sample tools: {', '.join(tool_names)}")
        else:
            print(f"[MCP ERROR] Unexpected response: {response}")
            raise ConnectionError(f"Failed to initialize MCP connection. Response: {response}")
    
    async def _list_tools(self):
        """List available tools from MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list"
        }
        
        response = await self._send_request(request)
        
        if response and "result" in response:
            tools = response["result"].get("tools", [])
            self.tools = {tool["name"]: tool for tool in tools}
    
    async def _send_request(self, request: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Send JSON-RPC request and wait for response"""
        if not self.process:
            raise RuntimeError("MCP server not started. Call start() first.")
        
        # Check if process is still running
        if self.process.returncode is not None:
            stderr_output = await self.process.stderr.read()
            error_msg = stderr_output.decode().strip() if stderr_output else "Unknown error"
            raise RuntimeError(f"Docker container exited (code: {self.process.returncode}): {error_msg}")
        
        request_str = json.dumps(request) + "\n"
        try:
            self.process.stdin.write(request_str.encode())
            await self.process.stdin.drain()
        except BrokenPipeError:
            stderr_output = await self.process.stderr.read()
            error_msg = stderr_output.decode().strip() if stderr_output else "Broken pipe"
            raise RuntimeError(f"Failed to send request to Docker container: {error_msg}")
        
        # Read response with timeout
        try:
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Timeout waiting for response from MCP server (>{timeout}s)")
        
        if not response_line:
            # Check if process exited
            if self.process.returncode is not None:
                stderr_output = await self.process.stderr.read()
                error_msg = stderr_output.decode().strip() if stderr_output else "Process exited"
                raise RuntimeError(f"Docker container exited: {error_msg}")
            return None
        
        try:
            response_text = response_line.decode().strip()
            if not response_text:
                return None
            response = json.loads(response_text)
            return response
        except json.JSONDecodeError as e:
            print(f"[MCP ERROR] Failed to parse response: {e}")
            print(f"[MCP ERROR] Raw response: {response_line.decode()}")
            return None
    
    async def _send_notification(self, notification: Dict[str, Any]):
        """Send JSON-RPC notification (no response expected)"""
        if not self.process:
            raise RuntimeError("MCP server not started. Call start() first.")
        
        notification_str = json.dumps(notification) + "\n"
        self.process.stdin.write(notification_str.encode())
        await self.process.stdin.drain()
    
    def _next_id(self) -> int:
        """Get next request ID"""
        self.request_id += 1
        return self.request_id
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        if not self.initialized:
            raise RuntimeError("MCP client not initialized. Call start() first.")
        
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not available. Available tools: {list(self.tools.keys())}")
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        response = await self._send_request(request)
        
        if response and "result" in response:
            return response["result"]
        elif response and "error" in response:
            error = response["error"]
            raise RuntimeError(f"MCP tool error: {error.get('message', 'Unknown error')} (code: {error.get('code', 'unknown')})")
        else:
            raise RuntimeError("Invalid response from MCP server")
    
    async def list_repositories(self, username: Optional[str] = None, per_page: int = 30) -> Dict[str, Any]:
        """List GitHub repositories using MCP tool"""
        
        # Use list_repositories tool if available
        if "list_repositories" in self.tools:
            try:
                print(f"[MCP] Using list_repositories tool to get all repos (including private)")
                args = {
                    "perPage": per_page,
                    "page": 1
                }
                if username:
                    args["username"] = username
                
                result = await self.call_tool("list_repositories", args)
                
                # Parse the MCP response
                if isinstance(result, dict) and "content" in result:
                    content_list = result.get("content", [])
                    if content_list and isinstance(content_list[0], dict):
                        text_content = content_list[0].get("text", "")
                        if text_content:
                            try:
                                import json
                                repos_data = json.loads(text_content)
                                # Handle different response formats
                                if isinstance(repos_data, list):
                                    repos = repos_data
                                elif isinstance(repos_data, dict):
                                    repos = repos_data.get("repositories", repos_data.get("items", []))
                                else:
                                    repos = []
                                
                                print(f"[MCP] Found {len(repos)} repositories (including private)")
                                return {
                                    "items": repos,
                                    "total_count": len(repos)
                                }
                            except json.JSONDecodeError as e:
                                print(f"[MCP ERROR] Failed to parse list_repositories response: {e}")
            except Exception as e:
                print(f"[MCP WARNING] list_repositories tool failed: {e}")
                print(f"[MCP] Falling back to search_repositories...")
        
        # Fallback: use search_repositories
        if username:
            # Search for user's repositories
            args = {
                "query": f"user:{username}",
                "perPage": per_page
            }
            print(f"[MCP] Searching public repositories for user: {username}")
            result = await self.call_tool("search_repositories", args)
            items = result.get("items", [])
            print(f"[MCP] Found {len(items)} public repositories")
            return result
        else:
            # Get authenticated user's repositories
            try:
                me_result = await self.call_tool("get_me", {})
                
                # Parse user info
                user_login = ""
                if isinstance(me_result, dict) and "content" in me_result:
                    content_list = me_result.get("content", [])
                    if content_list and isinstance(content_list[0], dict):
                        text_content = content_list[0].get("text", "")
                        if text_content:
                            try:
                                import json
                                user_data = json.loads(text_content)
                                user_login = user_data.get("login", "")
                            except (json.JSONDecodeError, KeyError) as e:
                                print(f"[MCP DEBUG] Failed to parse user data: {e}")
                
                if not user_login:
                    user_login = (
                        me_result.get("login") or 
                        me_result.get("username") or 
                        me_result.get("user") or
                        ""
                    )
                
                print(f"[MCP DEBUG] Authenticated user login: {user_login}")
                
                if user_login:
                    # Try multiple search query formats
                    search_queries = [
                        f"user:{user_login}",
                        f"user:{user_login} fork:false",
                        f"{user_login}",
                        f"owner:{user_login}",
                    ]
                    
                    all_items = []
                    for query in search_queries:
                        try:
                            args = {
                                "query": query,
                                "perPage": per_page
                            }
                            print(f"[MCP] Trying search query: {query}")
                            result = await self.call_tool("search_repositories", args)
                            
                            # Debug: print the full result structure
                            print(f"[MCP DEBUG] Search result type: {type(result)}")
                            if isinstance(result, dict):
                                print(f"[MCP DEBUG] Result keys: {list(result.keys())}")
                                # Print a sample of the result
                                result_str = str(result)[:500]
                                print(f"[MCP DEBUG] Result sample: {result_str}...")
                            
                            # Try different ways to extract items
                            items = []
                            if isinstance(result, dict):
                                # First try direct access
                                items = result.get("items", result.get("repositories", []))
                                
                                # If no items found, check if result is in content format (like get_me)
                                if not items and "content" in result:
                                    content_list = result.get("content", [])
                                    if content_list and isinstance(content_list[0], dict):
                                        text_content = content_list[0].get("text", "")
                                        if text_content:
                                            try:
                                                import json
                                                parsed = json.loads(text_content)
                                                print(f"[MCP DEBUG] Parsed content type: {type(parsed)}")
                                                if isinstance(parsed, list):
                                                    items = parsed
                                                    print(f"[MCP DEBUG] Found {len(items)} items in parsed list")
                                                elif isinstance(parsed, dict):
                                                    items = parsed.get("items", parsed.get("repositories", parsed.get("data", [])))
                                                    print(f"[MCP DEBUG] Found {len(items)} items in parsed dict")
                                            except Exception as e:
                                                print(f"[MCP DEBUG] Failed to parse content: {e}")
                                
                                # If still no items, check if result itself is a list
                                if not items and isinstance(result, list):
                                    items = result
                            
                            print(f"[MCP] Query '{query}' returned {len(items)} items")
                            if len(items) > 0:
                                print(f"[MCP DEBUG] First item sample: {str(items[0])[:200]}...")
                            
                            # Filter to only repos owned by the user
                            for item in items:
                                owner = item.get("owner", {})
                                owner_login = owner.get("login", "") if isinstance(owner, dict) else ""
                                full_name = item.get("fullName", item.get("full_name", ""))
                                
                                # Check if repo is owned by the user
                                if (owner_login and owner_login.lower() == user_login.lower()) or \
                                   (full_name and full_name.startswith(f"{user_login}/")):
                                    # Check if already have this repo
                                    existing = any(
                                        (item.get("fullName", item.get("full_name", "")) == 
                                         existing_item.get("fullName", existing_item.get("full_name", "")))
                                        for existing_item in all_items
                                    )
                                    if not existing:
                                        all_items.append(item)
                            
                            # If results, stop trying
                            if len(all_items) > 0:
                                break
                        except Exception as e:
                            print(f"[MCP DEBUG] Query '{query}' failed: {e}")
                            continue
                    
                    print(f"[MCP] Found {len(all_items)} public repositories for {user_login}")
                    
                    if len(all_items) == 0:
                        print(f"[MCP WARNING] No public repositories found for {user_login}")
                        print(f"[MCP WARNING] GitHub Search API only returns public repositories")
                        print(f"[MCP WARNING] If you have private repositories, they won't appear in search results")
                    
                    return {
                        "items": all_items,
                        "total_count": len(all_items)
                    }
                else:
                    print("[MCP WARNING] Could not determine user login")
                    return {"items": [], "total_count": 0}
            except Exception as e:
                print(f"[MCP ERROR] Failed to get user info: {e}")
                return {"items": [], "total_count": 0}
    
    async def get_file(self, owner: str, repo: str, path: str) -> Dict[str, Any]:
        """Get file content from GitHub using MCP tool"""
        # Use get_file_contents tool
        args = {
            "owner": owner,
            "repo": repo,
            "path": path
        }
        
        result = await self.call_tool("get_file_contents", args)
        return result
    
    async def create_file(self, owner: str, repo: str, path: str, content: str, message: str, branch: str = "main") -> Dict[str, Any]:
        """Create file in GitHub using MCP tool"""
        # Use create_or_update_file tool
        args = {
            "owner": owner,
            "repo": repo,
            "path": path,
            "content": content,
            "message": message,
            "branch": branch  # Add branch parameter (default to main)
        }
        
        print(f"[MCP DEBUG] Calling create_or_update_file with args: owner={owner}, repo={repo}, path={path}, branch={branch}")
        result = await self.call_tool("create_or_update_file", args)
        
        # Debug: print the actual result
        print(f"[MCP DEBUG] create_or_update_file result type: {type(result)}")
        if isinstance(result, dict):
            print(f"[MCP DEBUG] create_or_update_file result keys: {list(result.keys())}")
            
            # Check for errors
            if result.get("isError", False):
                error_text = ""
                if "content" in result:
                    content_list = result.get("content", [])
                    if content_list and isinstance(content_list[0], dict):
                        error_text = content_list[0].get("text", "Unknown error")
                raise RuntimeError(f"MCP tool error: {error_text}")
            
            print(f"[MCP DEBUG] create_or_update_file result: {str(result)[:500]}")
        else:
            print(f"[MCP DEBUG] create_or_update_file result: {str(result)[:500]}")
        
        return result
    
    async def update_file(self, owner: str, repo: str, path: str, content: str, message: str, branch: str = "main", sha: str = None) -> Dict[str, Any]:
        """Update file in GitHub using MCP tool"""
        # Use create_or_update_file tool
        args = {
            "owner": owner,
            "repo": repo,
            "path": path,
            "content": content,
            "message": message,
            "branch": branch  # Add branch parameter
        }
        
        # If SHA is provided (for updates), include it
        if sha:
            args["sha"] = sha
        
        print(f"[MCP DEBUG] Calling create_or_update_file (update) with args: owner={owner}, repo={repo}, path={path}, branch={branch}")
        result = await self.call_tool("create_or_update_file", args)
        
        # Check for errors
        if isinstance(result, dict) and result.get("isError", False):
            error_text = ""
            if "content" in result:
                content_list = result.get("content", [])
                if content_list and isinstance(content_list[0], dict):
                    error_text = content_list[0].get("text", "Unknown error")
            raise RuntimeError(f"MCP tool error: {error_text}")
        
        return result
    
    async def stop(self):
        """Stop the MCP server connection"""
        if self.process:
            self.process.stdin.close()
            await self.process.wait()
            self.process = None
            self.initialized = False
            print("[MCP] Disconnected from GitHub MCP Server")
