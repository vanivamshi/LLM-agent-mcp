# MCP Implementation - Real GitHub API and File System

A Model Context Protocol (MCP) implementation with **REAL** GitHub API and File System support, featuring task-based access pattern model with persona-based permissions.

## Personas

1. **Alex Chen (eng01)** - Engineering
   - GitHub: Read & Write
   - File System: Engineering folder

2. **Priya Nair (it01)** - IT
   - GitHub: Read Only
   - File System: IT folder

3. **Marco Diaz (sales01)** - Sales
   - GitHub: No access
   - File System: Sales folder

## Task Mapping

The system maps prompts to tasks:

- **Feature Development** → Engineering (eng01)
- **Production Support** → Engineering (eng01)
- **Incident/Ticket Resolution** → IT (it01)
- **Infrastructure Maintenance** → IT (it01)
- **Lead Generation** → Sales (sales01)
- **Proposal Development** → Sales (sales01)

## Setup

### Prerequisites

1. **Docker**: Ensure Docker is installed and running
   ```bash
   docker --version
   ```

2. **Pull the GitHub MCP Server Docker image**:
   ```bash
   docker pull ghcr.io/github/github-mcp-server
   ```

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your GitHub token:
```env
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
# Or use GITHUB_TOKEN for direct API calls (fallback)
GITHUB_TOKEN=your_github_token
```

To create a GitHub Personal Access Token:
- Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
- Generate a new token with `repo` scope for full access
- Copy the token and add it to your `.env` file

3. Run the application:
```bash
python3 main.py
```

### Docker-based GitHub MCP Server

The application now uses the **Docker-based GitHub MCP Server** by default. This provides:
- Official GitHub MCP server implementation
- Better tool coverage and reliability
- Automatic read-only mode for IT persona (it01)

The MCP server runs in a Docker container and communicates via stdio using the MCP (Model Context Protocol) JSON-RPC protocol.

**Note**: Make sure Docker is running before starting the application. The first run will pull the Docker image if not already available.

## Usage

### Interactive CLI

1. Select a persona when prompted
2. Enter prompts to process
3. The system will:
   - Map your prompt to a task
   - Determine required persona
   - Check permissions
   - Execute tool calls (GitHub and/or File System)

### Example Prompts

**Engineering (eng01):**
- `list_repositories` - List your GitHub repos
- `read file` - Read a file from GitHub (will prompt for owner/repo/path)
- `create file` - create a new feature in the repository
- `fix bug` - fix the bug in the code
- `raise ticket/file complaint` - raise an issue for IT to solve

**IT (it01):**
- `list_repositories` - List repos (read-only)
- `read file` - Read files from IT folder
- `list files` - List files in IT folder
- `read ticket` - reads the recent ticket and shows details
- `read ticket TKT-20250115143022-eng01` - reads a particular ticket
- `update ticket/modify ticket` - reads and updates content of the most recent ticket
- `close ticket/resolve ticket` - changes status of ticket to resolve and closes it
- `list tickets` - shows all tickets
- `list open tickets` - shows open/unresolved tickets
- `list resolved tickets` - shows resolved tickets

**Sales (sales01):**
- `list files` - List files in Sales folder
- `read file` - Read files from Sales folder
- `create file` - Create files in Sales folder
- `raise ticket/file complaint` - raise an issue for IT to solve

## Architecture

### Task-based Access Pattern Model

1. **Prompt → Task**: Maps user prompts to tasks using keyword matching
2. **Task → Persona**: Maps tasks to required personas
3. **Persona → Permissions**: Determines access based on persona
4. **Tool Calls**: Executes GitHub and/or File System operations
5. **Results**: Returns action results or data retrieval

### Permission Model

- **GitHub**: 
  - Engineering: Read & Write (requires GITHUB_TOKEN)
  - IT: Read Only (requires GITHUB_TOKEN)
  - Sales: No access

- **File System**:
  - Each persona has access only to their specific folder
  - Engineering: `persona_data/Engineering/`
  - IT: `persona_data/IT/`
  - Sales: `persona_data/Sales/`


### GitHub API

- **List Repositories**: `GET /user/repos` - Lists authenticated user's repositories
- **Get File**: `GET /repos/{owner}/{repo}/contents/{path}` - Reads file content
- **Create File**: `PUT /repos/{owner}/{repo}/contents/{path}` - Creates/updates files

All operations require `GITHUB_TOKEN` environment variable.

### File System

- **List Files**: Lists files in persona-specific folder
- **Read File**: Reads file content from persona folder
- **Write File**: Creates/updates files in persona folder
