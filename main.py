#!/usr/bin/env python3
import asyncio
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from mcp_client import RealMCPClient, PERSONAS, BASE_DIR

# Load environment variables from .env file
load_dotenv()

class MCPApplication:
    def __init__(self):
        self.current_user_id = "eng01"
        self.mcp_client = None
        # Store repo info for subsequent operations
        self.current_repo = {"owner": None, "repo": None}
        # Store create file location choice
        self._create_file_location = None
        self._pending_fs_create = None
        # Store event loop for async operations
        self._loop = None
    
    def select_persona(self):
        """Select persona for the session"""
        print("\n" + "=" * 50)
        print("Available Personas:")
        print("=" * 50)
        for user_id, persona in PERSONAS.items():
            print(f"{user_id}: {persona['name']} ({persona['team']}) - {persona['persona']}")
            print(f"   GitHub: {persona['permissions']['github']}")
            print(f"   FileSystem: {', '.join(persona['permissions']['filesystem'])}")
            print()
        
        while True:
            user_id = input("Select persona (eng01/it01/sales01): ").strip()
            if not user_id:
                print("[ERROR] Persona not selected. Please select a persona.")
                continue
            if user_id in PERSONAS:
                self.current_user_id = user_id
                # Initialize event loop before creating MCP client
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._loop = loop
                self.mcp_client = RealMCPClient(user_id)
                return
            print("[ERROR] Invalid persona")
    
    def process_prompt(self, prompt: str):
        """Process prompt"""
        print(f"\n[PROMPT] {prompt}")
        print("-" * 50)
        
        task = self.mcp_client.map_prompt_to_task(prompt)
        print(f"[TASK] {task}")
        
        required_persona = self.mcp_client.get_persona_for_task(task)
        if required_persona and required_persona != self.current_user_id:
            print(f"[WARNING] Task requires {PERSONAS[required_persona]['name']}")
        
        tool_calls = self._determine_tools(prompt)
        print(f"[TOOLS] {', '.join(tool_calls) if tool_calls else 'None'}")
        
        if not tool_calls:
            print("[ERROR] No tools determined. Use keywords: github, repository, file, folder")
            return []
        
        # Use existing event loop or create new one
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        self._loop = loop
        return loop.run_until_complete(self._execute_tools(tool_calls, prompt))
    
    def _determine_tools(self, prompt: str) -> list:
        """Determine tools needed"""
        import re
        p = prompt.lower()
        tools = []
        
        # Get persona permissions
        persona_permissions = self.mcp_client.persona["permissions"]
        has_github_access = persona_permissions.get("github") in ["read_only", "read_write"]
        
        # Check for ticket operations first before generic "read" or "file" checks
        # Ticket operations should only use filesystem which handles database tickets
        if any(w in p for w in ["read ticket", "view ticket", "show ticket", "list tickets", "show tickets", 
                                "raise ticket", "file complaint", "create ticket", "report issue", 
                                "modify ticket", "update ticket", "edit ticket", "close ticket", "resolve ticket"]):
            tools.append("filesystem")
            return tools  # return - ticket operations only need filesystem
        
        # Check for explicit GitHub keywords
        github_keywords = ["github", "repo", "repository", "code", "branch", "commit", "bug", "issue"]
        has_github_keyword = any(k in p for k in github_keywords)
        
        # Check for file system keywords (excluding "ticket" to avoid conflicts)
        filesystem_keywords = ["file", "folder", "document", "script", "doc", "template", "log", 
                               "troubleshoot", "incident", "maintenance", "infrastructure", 
                               "raise", "complaint", "report"]
        has_filesystem_keyword = any(k in p for k in filesystem_keywords)
        
        # Handle "read file" and "create file" - persona-specific routing
        if ("read" in p and "file" in p) or ("create" in p and "file" in p):
            if self.current_user_id == "eng01":
                # Engineering: try both GitHub and filesystem
                if has_github_access:
                    tools.append("github")
                tools.append("filesystem")
            elif self.current_user_id == "sales01":
                # Sales: only filesystem
                tools.append("filesystem")
            elif self.current_user_id == "it01":
                # IT: filesystem first, GitHub only if explicitly mentioned
                tools.append("filesystem")
                if has_github_keyword and has_github_access:
                    tools.append("github")
            else:
                if has_github_keyword or "github" in p:
                    if has_github_access:
                        tools.append("github")
                elif any(path_indicator in p for path_indicator in ["/", "./", "../", "folder", "directory"]):
                    tools.append("filesystem")
                else:
                    tools.append("filesystem")
        else:
            if has_github_keyword:
                tools.append("github")
            
            # Check if it is a write operation or local file operation
            if has_filesystem_keyword:
                # Check if it is a write operation
                if any(w in p for w in ["write", "create", "add", "make", "update", "modify"]):
                    tools.append("filesystem")
                # Check if it is a read operation with local file indicators
                elif any(indicator in p for indicator in ["folder", "directory", "/", "./", "../"]):
                    tools.append("filesystem")
                # For read operations without clear indicators, check persona
                elif "read" in p:
                    # If persona doesn't have GitHub access, use filesystem
                    if self.mcp_client.persona["permissions"]["github"] == "none":
                        tools.append("filesystem")
                    # If persona has GitHub access, add both and let execution decide
                    else:
                        tools.extend(["github", "filesystem"])
                else:
                    tools.append("filesystem")
        
        # Task-based tool assignment
        task = self.mcp_client.map_prompt_to_task(prompt)
        if task in ["Incident/Ticket Resolution", "Infrastructure Maintenance"]:
            # IT tasks need both GitHub to investigate and filesystem for logs/scripts
            tools.extend(["github", "filesystem"])
        elif task in ["Feature Development", "Production Support"]:
            # Engineering tasks need both
            tools.extend(["github", "filesystem"])
        elif task in ["Lead Generation", "Proposal Development"]:
            # Sales tasks need filesystem
            tools.append("filesystem")
        
        # Check for file paths (absolute or relative)
        # Pattern: /path/to/file or ./file or ../file or file.txt
        file_path_pattern = r'(?:^|\s)(?:/|\./|\.\./)?[\w/\.\-]+\.(?:txt|md|py|js|json|yaml|yml|sh|csv|docx?|pdf)(?:\s|$)'
        if re.search(file_path_pattern, prompt):
            tools.append("filesystem")
        
        # Check for absolute paths
        if prompt.startswith('/') or '~/' in prompt:
            tools.append("filesystem")
        
        return list(dict.fromkeys(tools))
    
    async def _execute_tools(self, tools: list, prompt: str):
        """Execute tool operations"""
        results = []
        p = prompt.lower()
        
        # Check if this is a ticket creation - then only execute filesystem
        is_ticket_creation = any(w in p for w in ["raise ticket", "file complaint", "create ticket", "report issue", "file a complaint"])
        
        # For "read file" and "create file" with eng01, try GitHub first, then filesystem
        is_read_file = "read" in p and "file" in p
        is_create_file = "create" in p and "file" in p
        github_first = (is_read_file or is_create_file) and self.current_user_id == "eng01" and "github" in tools
        
        for tool in tools:
            try:
                if tool == "github":
                    # Skip GitHub operations if ticket creation
                    if is_ticket_creation:
                        continue
                    result = await self._do_github(p)
                    # If result is None, it means the operation was deferred (e.g., create file asking for location)
                    if result is not None:
                        # Check if result is an error
                        is_error = isinstance(result, dict) and result.get("error")
                        if not is_error:
                            results.append({"tool": "github", "success": True, "data": result})
                            # If GitHub operation was successful and user chose github only, don't try filesystem
                            if github_first and result:
                                # Check if user explicitly chose github not both
                                if "create" in p and "file" in p:
                                    # Check if we should skip filesystem
                                    break
                        else:
                            results.append({"tool": "github", "success": False, "error": result.get("error", "Unknown error")})
                    else:
                        # Operation deferred user chose filesystem, continue to filesystem
                        pass
                elif tool == "filesystem":
                    # For eng01 reading/creating file, check if GitHub was chosen
                    if is_create_file and self._create_file_location == "github":
                        # User explicitly chose github only, skip filesystem
                        continue
                    # For eng01 reading file, only try filesystem if GitHub did not work
                    if github_first and results and any(r.get("tool") == "github" and r.get("success") for r in results):
                        # GitHub already handled it
                        continue
                    
                    # If "both" was chosen and we have pending filesystem create
                    if is_create_file and self._create_file_location == "both" and self._pending_fs_create:
                        folder = self.mcp_client.persona["permissions"]["filesystem"][0]
                        result = self.mcp_client.filesystem_write_file(
                            folder,
                            self._pending_fs_create["filename"],
                            self._pending_fs_create["content"]
                        )
                        self._pending_fs_create = None
                    else:
                        result = self._do_filesystem(p)
                        results.append({"tool": "filesystem", "success": True, "data": result})
                    # If ticket was created, stop here
                    if is_ticket_creation and result.get("ticket_id"):
                        break
            except PermissionError as e:
                results.append({"tool": tool, "success": False, "error": str(e)})
            except Exception as e:
                results.append({"tool": tool, "success": False, "error": str(e)})
        
        return results
    
    async def _do_github(self, prompt: str):
        """Execute GitHub operations"""
        # List repos
        if "list" in prompt or "show" in prompt:
            return await self.mcp_client.github_list_repos()
        
        # Fix/update file - should read first, then update
        if "fix" in prompt or "update" in prompt or "modify" in prompt:
            if not self.current_repo["owner"]:
                print("[INPUT] Enter GitHub owner/username:")
                owner = input("> ").strip()
                print("[INPUT] Enter repository name:")
                repo = input("> ").strip()
                self.current_repo = {"owner": owner, "repo": repo}
            
            print("[INPUT] Enter file path to fix (e.g., main.py):")
            path = input("> ").strip()
            if not path:
                return {"error": "File path required"}
            
            # Read the existing file
            print("[INFO] Reading existing file...")
            file_data = await self.mcp_client.github_get_file(
                self.current_repo["owner"],
                self.current_repo["repo"],
                path
            )
            
            print(f"\n[INFO] Current file content ({file_data.get('size', 0)} bytes):")
            print("-" * 50)
            print(file_data.get("content", "")[:500])
            if len(file_data.get("content", "")) > 500:
                print("... (truncated)")
            print("-" * 50)
            
            print("\n[INPUT] Enter new/fixed content:")
            content = input("> ").strip()
            if not content:
                print("[WARNING] No content provided, using original content")
                content = file_data.get("content", "")
            
            # Update the file
            result = await self.mcp_client.github_update_file(
                self.current_repo["owner"],
                self.current_repo["repo"],
                path,
                content,
                f"Fixed: {prompt[:50]}"
            )
            
            # After successful update, read and display the updated file
            if result and not result.get("error"):
                print("\n[INFO] File updated successfully. Reading updated file...")
                updated_file_data = await self.mcp_client.github_get_file(
                    self.current_repo["owner"],
                    self.current_repo["repo"],
                    path
                )
                print(f"\n[INFO] Updated file content ({updated_file_data.get('size', 0)} bytes):")
                print("-" * 50)
                print(updated_file_data.get("content", ""))
                print("-" * 50)
                # Include updated content in result
                result["updated_content"] = updated_file_data.get("content", "")
            
            return result
        
        # Read file - need owner/repo/path
        if "read" in prompt or "get" in prompt or "view" in prompt:
            if not self.current_repo["owner"]:
                print("[INPUT] Enter GitHub owner/username:")
                owner = input("> ").strip()
                print("[INPUT] Enter repository name:")
                repo = input("> ").strip()
                self.current_repo = {"owner": owner, "repo": repo}
            
            print("[INPUT] Enter file path (e.g., README.md):")
            path = input("> ").strip() or "README.md"
            
            return await self.mcp_client.github_get_file(
                self.current_repo["owner"],
                self.current_repo["repo"],
                path
            )
        
        # Create/write file (new files)
        if any(w in prompt for w in ["create", "write", "add", "implement"]):
            # Ask user where to create the file
            print("[INPUT] Where to create file? (github/filesystem/both) [default: filesystem]:")
            location = input("> ").strip().lower() or "filesystem"
            
            # Store location choice for execution logic
            self._create_file_location = location
            
            if location in ["github", "both"]:
                if not self.current_repo["owner"]:
                    print("[INPUT] Enter GitHub owner/username:")
                    owner = input("> ").strip()
                    print("[INPUT] Enter repository name:")
                    repo = input("> ").strip()
                    self.current_repo = {"owner": owner, "repo": repo}
            
            print("[INPUT] Enter file path to create (e.g., new_file.txt):")
            path = input("> ").strip() or "test_file.txt"
            print("[INPUT] Enter file content:")
            content = input("> ").strip() or "# Test file created via MCP"
            
            try:
                github_result = await self.mcp_client.github_create_file(
                self.current_repo["owner"],
                self.current_repo["repo"],
                path,
                content,
                "Created via MCP"
            )
                    
                # Store content and path for filesystem if "both"
                if location == "both":
                    self._pending_fs_create = {"filename": path, "content": content}
                
                if location == "github":
                    return github_result
                else:
                    # Both - return github result, filesystem will be handled separately
                    return {"github": github_result, "location": "both"}
            except Exception as e:
                return {"error": str(e)}
            
            # If only filesystem or location not specified, return None to let filesystem handler take over
            return None
        
        # List repos
        return await self.mcp_client.github_list_repos()
    
    def _do_filesystem(self, prompt: str):
        """Execute filesystem operations"""
        import re
        from pathlib import Path
        
        # Check if prompt contains a file path
        file_path = None
        file_path_pattern = r'(?:^|\s)((?:/|\./|\.\./)?[\w/\.\-]+\.(?:txt|md|py|js|json|yaml|yml|sh|csv|docx?|pdf))(?:\s|$)'
        match = re.search(file_path_pattern, prompt, re.IGNORECASE)
        if match:
            file_path = match.group(1).strip()
        
        # Check for absolute paths
        if prompt.startswith('/') or '/home/' in prompt or '/home' in prompt.lower():
            # Extract path from prompt
            parts = prompt.split()
            for part in parts:
                if part.startswith('/'):
                    # Use the path exactly as provided
                    file_path = part
                    break
        
        folder = self.mcp_client.persona["permissions"]["filesystem"][0]
        
        # Raise ticket/complaint - for Engineering and Sales (using database)
        if any(w in prompt for w in ["raise ticket", "file complaint", "create ticket", "report issue", "file a complaint"]):
            print("[INPUT] Enter ticket/complaint title:")
            title = input("> ").strip() or "New Ticket"
            print("[INPUT] Enter ticket/complaint description:")
            description = input("> ").strip() or "No description provided"
            print("[INPUT] Enter priority (Low/Medium/High) [default: Medium]:")
            priority = input("> ").strip() or "Medium"
            print("[INPUT] Enter category (optional):")
            category = input("> ").strip() or None
            
            # Create ticket in database
            ticket = self.mcp_client.create_ticket(title, description, priority, category)
            print(f"[INFO] Ticket created: {ticket['ticket_id']}")
            return ticket
        
        # List tickets
        if "list tickets" in prompt or "show tickets" in prompt or "tickets" in prompt:
            # Check for status filter
            status = None
            if "open" in prompt:
                status = "Open"
            elif "closed" in prompt or "resolved" in prompt:
                status = "Resolved"
            
            tickets = self.mcp_client.list_tickets(status=status)
            if tickets:
                    return {
                    "count": len(tickets),
                    "tickets": tickets,
                    "filter": status or "All"
                    }
            else:
                return {"message": "No tickets found", "filter": status or "All"}
        
        # Read ticket - get most recent or by ID
        if "read ticket" in prompt or "view ticket" in prompt or "show ticket" in prompt:
            # Check if ticket ID is provided in prompt
            import re
            # Use case-insensitive search and match the full ticket ID pattern
            ticket_id_match = re.search(r'TKT-\d+-\w+', prompt, re.IGNORECASE)
            ticket_id = ticket_id_match.group(0) if ticket_id_match else None
            # Strip any whitespace
            if ticket_id:
                ticket_id = ticket_id.strip()
            
            ticket = self.mcp_client.get_ticket(ticket_id)
            if ticket:
                return ticket
            else:
                return {"error": "No ticket found"}
        
        # Modify/update ticket
        if any(w in prompt for w in ["modify ticket", "update ticket", "edit ticket", "close ticket", "resolve ticket"]):
            # Get most recent ticket or extract ticket ID
            import re
            # Use case-insensitive search and match the full ticket ID pattern
            ticket_id_match = re.search(r'TKT-\d+-\w+', prompt, re.IGNORECASE)
            ticket_id = ticket_id_match.group(0) if ticket_id_match else None
            # Strip any whitespace
            if ticket_id:
                ticket_id = ticket_id.strip()
            
            if not ticket_id:
                # Get most recent ticket
                ticket = self.mcp_client.get_ticket()
                if not ticket:
                    return {"error": "No ticket found to modify"}
                ticket_id = ticket['ticket_id']
            
            # Debug: print extracted ticket_id
            print(f"[DEBUG] Extracted ticket_id: {ticket_id}")
            
            # Get current ticket
            current_ticket = self.mcp_client.get_ticket(ticket_id)
            if not current_ticket:
                return {"error": f"Ticket not found: {ticket_id}"}
            
            # Debug: verify we got the correct ticket
            if current_ticket['ticket_id'] != ticket_id:
                print(f"[DEBUG] WARNING: Requested ticket {ticket_id} but got {current_ticket['ticket_id']}")
                return {"error": f"Ticket ID mismatch: requested {ticket_id} but got {current_ticket['ticket_id']}"}
            
            print(f"\n[INFO] Current ticket: {current_ticket['ticket_id']}")
            print(f"Title: {current_ticket['title']}")
            print(f"Status: {current_ticket['status']}")
            print(f"Priority: {current_ticket.get('priority', 'Medium')}")
            print("-" * 50)
            
            # Determine what to update
            status = None
            if "close" in prompt or "resolve" in prompt:
                status = "Resolved"
            
            print("[INPUT] Enter update text (or press Enter for status update only):")
            update_text = input("> ").strip() or None
            
            print("[INPUT] Enter new priority (Low/Medium/High) or press Enter to keep current:")
            new_priority = input("> ").strip() or None
            
            # Update ticket in database
            updated_ticket = self.mcp_client.update_ticket(
                ticket_id, 
                update_text=update_text,
                status=status,
                priority=new_priority
            )
            
            if updated_ticket:
                print(f"[INFO] Ticket updated: {ticket_id}")
                return updated_ticket
            else:
                return {"error": "Failed to update ticket"}
        
        # Troubleshoot/incident operations - read incident logs (for IT only)
        if "troubleshoot" in prompt or "incident" in prompt or ("ticket" in prompt and "raise" not in prompt and "file" not in prompt):
            # Look for incident log files
            files = self.mcp_client.filesystem_list_files(folder)
            log_files = [f for f in files.get("files", []) if "log" in f["name"].lower() or "incident" in f["name"].lower()]
            
            if log_files:
                # Read the first log file
                log_file = log_files[0]
                print(f"[FS] Reading incident log: {log_file['name']}")
                return self.mcp_client.filesystem_read_file(folder, log_file["name"])
            else:
                # If no log files, list all files
                return files
        
        # Read file - if path is provided, read it directly
        if "read" in prompt or "open" in prompt or "view" in prompt or file_path:
            if file_path:
                # Handle absolute paths or paths relative to project root
                path_obj = Path(file_path)
                if path_obj.is_absolute():
                    # Absolute path - try exact path first
                    if path_obj.exists() and path_obj.is_file():
                        print(f"[FS] Reading absolute path: {file_path}")
                        content = path_obj.read_text()
                        return {
                            "filename": path_obj.name,
                            "path": str(path_obj),
                            "size": path_obj.stat().st_size,
                            "content": content
                        }
                    else:
                        # Try case-insensitive match for directories
                        try:
                            parts = path_obj.parts
                            current = Path(parts[0])
                            
                            for part in parts[1:]:
                                if current.exists():
                                    # Find case-insensitive match
                                    found = None
                                    for item in current.iterdir():
                                        if item.name.lower() == part.lower():
                                            found = item
                                            break
                                    if found:
                                        current = found
                                    else:
                                        # If not found, try exact match
                                        current = current / part
                                else:
                                    current = current / part
                            
                            if current.exists() and current.is_file():
                                print(f"Reading absolute path: {current}")
                                content = current.read_text()
                                return {
                                    "filename": current.name,
                                    "path": str(current),
                                    "size": current.stat().st_size,
                                    "content": content
                                }
                        except Exception as e:
                            pass
                        
                        return {"error": f"File not found: {file_path}"}
                else:
                    # Relative path - try in persona folder first, then project root
                    persona_path = BASE_DIR / folder / path_obj
                    project_path = Path(__file__).parent / path_obj
                    
                    if persona_path.exists() and persona_path.is_file():
                        return self.mcp_client.filesystem_read_file(folder, path_obj.name)
                    elif project_path.exists() and project_path.is_file():
                        print(f"Reading from project root: {file_path}")
                        content = project_path.read_text()
                        return {
                            "filename": project_path.name,
                            "path": str(project_path),
                            "size": project_path.stat().st_size,
                            "content": content
                        }
                    else:
                        return {"error": f"File not found: {file_path}"}
            else:
                # No path provided - try to extract filename from prompt
                files = self.mcp_client.filesystem_list_files(folder)
                if not files.get("files"):
                    return {"error": "No files found"}
                
                # Match filename from prompt
                prompt_lower = prompt.lower()
                matched_file = None
                
                # Look for filename in prompt (e.g., "read the abstract file" -> "abstract")
                for file_info in files["files"]:
                    filename_lower = file_info["name"].lower()
                    # Check if filename (without extension) is in prompt
                    filename_no_ext = Path(file_info["name"]).stem.lower()
                    if filename_lower in prompt_lower or filename_no_ext in prompt_lower:
                        matched_file = file_info
                        break
                
                # If no match found, match partial matches
                if not matched_file:
                    for file_info in files["files"]:
                        filename_lower = file_info["name"].lower()
                        filename_no_ext = Path(file_info["name"]).stem.lower()
                        # Check if any word from filename is in prompt
                        filename_words = filename_no_ext.split('_')
                        for word in filename_words:
                            if word and word in prompt_lower and len(word) > 2:
                                matched_file = file_info
                                break
                        if matched_file:
                            break
                
                # If still no match, use first file
                if not matched_file:
                    matched_file = files["files"][0]
                    print(f"[INFO] No specific file matched, reading first file: {matched_file['name']}")
                else:
                    print(f"[FS] Reading matched file: {matched_file['name']}")
                
                return self.mcp_client.filesystem_read_file(folder, matched_file["name"])
        
        # List files
        if "list" in prompt or "show" in prompt:
            return self.mcp_client.filesystem_list_files(folder)
        
        # Write file
        if any(w in prompt for w in ["create", "write", "add", "make"]):
            print("[INPUT] Enter filename:")
            filename = input("> ").strip() or "new_file.txt"
            print("[INPUT] Enter content:")
            content = input("> ").strip() or f"Created via MCP at {folder}"
            
            return self.mcp_client.filesystem_write_file(folder, filename, content)
        
        # List files
        return self.mcp_client.filesystem_list_files(folder)
    
    def display_results(self, results: list):
        """Display results"""
        print("\n" + "=" * 50)
        print("RESULTS:")
        print("=" * 50)
        
        for r in results:
            tool = r["tool"].upper()
            if r.get("success"):
                print(f"\n[OK] {tool} SUCCESS:")
                data = r.get("data", {})
                
                # Handle ticket updates
                if isinstance(data, dict) and "ticket_id" in data and "updates" in data:
                    ticket = data
                    print(f"Ticket ID: {ticket.get('ticket_id')}")
                    print(f"Title: {ticket.get('title')}")
                    print(f"Status: {ticket.get('status')}")
                    print(f"Priority: {ticket.get('priority', 'Medium')}")
                    print(f"Updated at: {ticket.get('updated_at')}")
                    
                    # Show all updates
                    updates = ticket.get('updates', [])
                    if updates:
                        print(f"\nUpdate History ({len(updates)} updates):")
                        print("-" * 50)
                        for idx, update in enumerate(updates, 1):
                            marker = ">>> LATEST UPDATE <<<" if idx == len(updates) else ""
                            print(f"{marker}")
                            print(f"  [{idx}] {update.get('text', 'N/A')}")
                            print(f"      By: {update.get('by', 'N/A')} at {update.get('at', 'N/A')}")
                            if marker:
                                print("-" * 50)
                    else:
                        print("\nNo updates yet.")
                else:
                    # For other results, use normal display
                    output = json.dumps(data, indent=2)
                    if len(output) > 1000:
                        print(output[:1000])
                        print(f"\n... (truncated, total length: {len(output)} characters)")
                    else:
                        print(output)
            else:
                print(f"\n[ERROR] {tool} FAILED:")
                print(f"   {r.get('error', 'Unknown error')}")
        
        print("=" * 50)
    
    def show_help(self):
        """Show example prompts"""
        print("\n" + "=" * 60)
        print("EXAMPLE PROMPTS BY PERSONA:")
        print("=" * 60)
        
        print("\n[ENGINEERING - eng01]")
        print("-" * 60)
        print("  • list repositories - List your GitHub repos")
        print("  • read file - Read a file from GitHub")
        print("  • create file - Create a new file in repository")
        print("  • raise ticket - Raise an issue for IT")
        
        print("\n[IT - it01]")
        print("-" * 60)
        print("  • list repositories - List repos (read-only)")
        print("  • list files - List files in IT folder")
        print("  • read ticket - Read ticket details")
        print("  • list tickets - Show all tickets")
        print("  • resolve ticket - Close and resolve a ticket")
        
        print("\n[SALES - sales01]")
        print("-" * 60)
        print("  • list files - List files in Sales folder")
        print("  • create proposal - Create proposal files")
        print("  • raise ticket - Raise an issue for IT")
        
        print("\n" + "=" * 60)
        print("Commands: <prompt> | persona | help | quit")
        print("=" * 60)
    
    def run(self):
        """Main loop"""
        print("=" * 50)
        print("MCP Application - REAL GitHub + FileSystem")
        print("=" * 50)
        
        self.select_persona()
        
        print("\nCommands: <prompt> | persona | help | quit")
        print("Type 'help' for example prompts")
        print("=" * 50)
    
        while True:
            try:
                prompt = input("\n> ").strip()
            
                if not prompt:
                    continue
            
                if prompt.lower() in ['quit', 'exit', 'q']:
                    break
                
                if prompt.lower() in ['help', 'h', '?']:
                    self.show_help()
                    continue
                
                if prompt.lower() == 'persona':
                    self.select_persona()
                    continue
                
                results = self.process_prompt(prompt)
                self.display_results(results)
                
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                print(f"[ERROR] {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    app = MCPApplication()
    app.run()
