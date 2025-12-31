# RoboMonkey MCP Quick Start Guide
## For Beginners - Step by Step

This guide assumes you're new to AI coding tools, Docker, and command-line tools. We'll walk through everything step by step.

---

## What You'll Need

- A computer with at least 8GB RAM
- About 30 minutes
- Internet connection
- Basic ability to copy/paste commands

---

## Step 1: Open Your Terminal

### On Mac:
- Press `Cmd + Space`
- Type "Terminal"
- Press Enter

### On Windows:
- Press `Windows + R`
- Type "cmd" or "powershell"
- Press Enter

### On Linux:
- Press `Ctrl + Alt + T`

**💡 Tip:** Keep this terminal window open for all the steps below!

---

## Step 2: Check What You Have Installed

Copy and paste these commands one at a time. Press Enter after each:

```bash
# Check Python version (need 3.11 or higher)
python3 --version
```

**Expected:** `Python 3.11.x` or higher

**If you get an error:**
- **Mac:** Install from https://www.python.org/downloads/
- **Windows:** Install from https://www.python.org/downloads/
- **Linux:** Run `sudo apt install python3.11` (Ubuntu/Debian)

```bash
# Check if Docker is installed
docker --version
```

**Expected:** `Docker version 20.x.x` or higher

**If you get an error:**
- **Mac/Windows:** Install Docker Desktop from https://www.docker.com/products/docker-desktop
- **Linux:** Follow https://docs.docker.com/engine/install/

```bash
# Check if git is installed
git --version
```

**Expected:** `git version 2.x.x` or higher

**If you get an error:**
- **Mac:** Run `xcode-select --install`
- **Windows:** Install from https://git-scm.com/download/win
- **Linux:** Run `sudo apt install git`

---

## Step 3: Install Ollama (For AI Embeddings)

### Mac/Linux:

```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

### Windows:

Download and install from: https://ollama.ai/download/windows

### Verify Installation:

```bash
ollama --version
```

**Expected:** Version number appears

**💡 Tip:** Ollama is like a local AI brain that helps understand your code!

---

## Step 4: Download RoboMonkey

```bash
# Go to your home directory
cd ~

# Download RoboMonkey
git clone https://github.com/yourusername/robomonkey-mcp.git

# Go into the folder
cd robomonkey-mcp
```

**💡 Tip:** This creates a folder called `robomonkey-mcp` in your home directory with all the files you need.

---

## Step 5: Start the Database

```bash
# Start PostgreSQL database
docker-compose up -d
```

**Expected:** You'll see messages about downloading and starting containers.

**💡 What's happening?**
- Docker is downloading a database program called PostgreSQL
- The `-d` means "run in background" so you can keep using your terminal
- This might take 2-5 minutes the first time

**Check if it's running:**

```bash
docker ps
```

**Expected:** You should see a line with "postgres" in it

**If something went wrong:**
```bash
# Stop everything
docker-compose down

# Try again
docker-compose up -d

# Check logs if still failing
docker-compose logs
```

---

## Step 6: Set Up Python Environment

```bash
# Create a virtual environment (keeps things organized)
python3 -m venv .venv

# Activate it (Mac/Linux)
source .venv/bin/activate

# Activate it (Windows)
.venv\Scripts\activate
```

**💡 What's a virtual environment?**
Think of it like a separate workspace just for this project, so it doesn't mess with other Python stuff on your computer.

**You'll know it worked when:**
Your command line shows `(.venv)` at the start, like:
```
(.venv) user@computer:~/robomonkey-mcp$
```

**Install RoboMonkey:**

```bash
pip install -e .
```

**Expected:** Lots of text scrolling by, then "Successfully installed robomonkey-mcp"

**💡 Tip:** This installs all the pieces RoboMonkey needs to run.

---

## Step 7: Configure RoboMonkey

```bash
# Copy the example configuration
cp .env.example .env

# Open it in a text editor
# Mac:
open .env

# Windows:
notepad .env

# Linux:
nano .env
```

**Important settings to check:**

```env
# If PostgreSQL is running in Docker (leave as-is):
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# If you changed the Docker port, update 5433 to match

# Leave these as-is for now:
EMBEDDINGS_MODEL=snowflake-arctic-embed2:latest
EMBEDDINGS_DIMENSION=1024
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100
```

**💡 Tip:** Only change DATABASE_URL if you know you need to. The defaults work for most people!

Save and close the file.

---

## Step 8: Download the AI Model

```bash
# This downloads the AI model Ollama will use
ollama pull snowflake-arctic-embed2:latest
```

**Expected:** A progress bar showing download (might take 5-10 minutes)

**💡 What's happening?**
You're downloading an AI model that can "understand" code. It's about 2GB in size.

**Verify it worked:**

```bash
ollama list
```

**Expected:** You should see `snowflake-arctic-embed2:latest` in the list

---

## Step 9: Initialize the Database

```bash
# Make sure you're in the robomonkey-mcp folder and .venv is activated
# You should see (.venv) at the start of your prompt

# Initialize
robomonkey db init
```

**Expected:**
```
✅ Database connection successful!
✅ pgvector extension available
✅ Control schema initialized
```

**If you get an error:**

```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # Mac/Linux
.venv\Scripts\activate     # Windows

# Make sure Docker is running
docker ps

# Check if PostgreSQL is ready
docker logs robomonkey-postgres
```

**Test the connection:**

```bash
robomonkey db ping
```

**Expected:**
```
✅ Database connection successful!
✅ pgvector extension available (version X.X.X)
✅ Control schema initialized
```

---

## Step 10: Index Your First Project

Now let's index some actual code!

```bash
# Replace /path/to/your/project with your actual project path
# For example: /Users/john/projects/my-app
# Or: C:\Users\john\projects\my-app (Windows)

robomonkey index --repo /path/to/your/project --name myproject
```

**Examples:**

```bash
# Mac/Linux example
robomonkey index --repo ~/projects/my-webapp --name mywebapp

# Windows example  
robomonkey index --repo C:\Users\YourName\projects\my-app --name myapp
```

**💡 Tips:**
- Use a project with at least 50-100 files for best results
- The name (after `--name`) can be anything you want
- This will take 1-10 minutes depending on project size

**Expected output:**
```
Scanning repository...
Found 234 files
Parsing Python files: 45/45
Parsing JavaScript files: 123/123
✅ Indexed 234 files, 1,234 symbols
```

**Check what got indexed:**

```bash
robomonkey status --name myproject
```

---

## Step 11: Generate AI Embeddings

This step teaches the AI to understand your code:

```bash
# Replace 'myproject' with the name you used above
# Replace 'robomonkey_myproject' with 'robomonkey_' + your project name

python scripts/embed_repo_direct.py myproject robomonkey_myproject
```

**💡 What's happening?**
The AI is reading every piece of your code and learning what it does. This lets you search your code using natural language later!

**Expected output:**
```
Starting embeddings for myproject (schema: robomonkey_myproject)
============================================================
Using model: snowflake-arctic-embed2:latest
Max chunk length: 8192 chars
Batch size: 100
Embedding dimensions: 1024
============================================================
Embedding 1234 chunks in batches of 100...
  ✓ Batch 1: Embedded 100/1234 chunks
  ✓ Batch 2: Embedded 200/1234 chunks
  ...
✓ Completed: Embedded 1234 chunks
```

**💡 This might take a while:**
- Small project (100 files): 5-10 minutes
- Medium project (500 files): 20-30 minutes  
- Large project (1000+ files): 45-60 minutes

**You can safely close your terminal and come back - just run the command again and it will pick up where it left off!**

---

## Step 12: Test It Works!

Let's make sure everything is working:

```bash
# Test 1: List your repositories
robomonkey repo ls
```

**Expected:**
```
Indexed Repositories:
  - myproject (robomonkey_myproject)
    Files: 234
    Symbols: 1,234
    Last indexed: 2025-12-31 08:00:00
```

**Test 2: Search your code**

```bash
python -c "
import asyncio
from robomonkey_mcp.retrieval.hybrid_search import hybrid_search

async def test():
    results = await hybrid_search(
        query='function that handles login',
        repo_name='myproject',
        database_url='postgresql://postgres:postgres@localhost:5433/robomonkey',
        top_k=5
    )
    print(f'Found {len(results)} results:')
    for r in results:
        print(f'  {r[\"file_path\"]}:{r[\"start_line\"]}')

asyncio.run(test())
"
```

**💡 Change the query to search for something you know exists in your code!**

**Expected:** List of files and line numbers where matching code was found

---

## Step 13: Use It With Your AI Coding Tool

### For Claude Desktop:

1. **Find the config file:**
   - Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. **Create or edit the file:**

```json
{
  "mcpServers": {
    "robomonkey": {
      "command": "/Users/yourname/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/robomonkey"
      }
    }
  }
}
```

**💡 Important:** Replace `/Users/yourname/robomonkey-mcp/.venv/bin/python` with your actual path!

**To find your path:**
```bash
# Mac/Linux
cd ~/robomonkey-mcp
pwd
# Copy this path and add /.venv/bin/python at the end

# Windows
cd C:\Users\YourName\robomonkey-mcp
cd
# Copy this path and add \.venv\Scripts\python.exe at the end
```

3. **Restart Claude Desktop**

4. **Test it:**

In Claude Desktop, try asking:
```
"Search my project for authentication functions"
```

Claude should now use RoboMonkey to find and show you the relevant code!

### For VS Code with Cline:

1. **Install Cline extension** from VS Code marketplace

2. **Open VS Code Settings** (Cmd/Ctrl + ,)

3. **Search for "cline mcp"**

4. **Edit settings.json** and add:

```json
{
  "cline.mcpServers": {
    "robomonkey": {
      "command": "/path/to/robomonkey-mcp/.venv/bin/python",
      "args": ["-m", "robomonkey_mcp.mcp.server"]
    }
  }
}
```

5. **Reload VS Code**

---

## Common "Oops!" Moments and Fixes

### "Command not found: robomonkey"

**Fix:**
```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # Mac/Linux
.venv\Scripts\activate     # Windows

# You should see (.venv) at the start of your command line
```

### "Docker is not running"

**Fix:**
```bash
# Mac/Windows: Open Docker Desktop app
# Linux: 
sudo systemctl start docker
```

### "Port already in use"

**Fix:**
```bash
# Something else is using port 5433
# Option 1: Stop other PostgreSQL
sudo systemctl stop postgresql  # Linux
brew services stop postgresql   # Mac

# Option 2: Change the port in docker-compose.yml
# Edit the file and change "5433:5432" to "5434:5432"
# Then update .env to use 5434 instead of 5433
```

### "Embeddings taking forever"

**This is normal!** Large projects can take 30+ minutes. 

**To speed it up:**
```bash
# Edit .env and increase batch size
nano .env
# Change: EMBEDDING_BATCH_SIZE=200

# Then run embedding again
```

### "Can't find my project folder"

**To find full paths:**
```bash
# Mac/Linux
cd /path/to/your/project
pwd
# Copy the output

# Windows
cd C:\path\to\your\project
cd
# Copy the output
```

---

## What to Do Next

1. **Index more projects:**
   ```bash
   robomonkey index --repo /path/to/another/project --name project2
   python scripts/embed_repo_direct.py project2 robomonkey_project2
   ```

2. **Set up the daemon for automatic updates:**
   - See [INSTALL.md](INSTALL.md#b-daemon-setup)

3. **Learn advanced searches:**
   - See [USER_GUIDE.md](USER_GUIDE.md#usage-examples)

---

## Getting Help

**Something not working?**

1. **Check the logs:**
   ```bash
   # Database logs
   docker logs robomonkey-postgres
   
   # Recent commands
   history | tail -20
   ```

2. **Ask for help:**
   - Include what command you ran
   - Include the error message
   - Include output of: `docker ps` and `robomonkey db ping`

3. **Start over (last resort):**
   ```bash
   # Stop everything
   docker-compose down
   
   # Remove virtual environment
   rm -rf .venv
   
   # Start from Step 5 again
   ```

---

## Cheat Sheet - Commands You'll Use Often

```bash
# Activate environment (do this every time you open a new terminal)
source .venv/bin/activate

# Check what's indexed
robomonkey repo ls

# Check database connection
robomonkey db ping

# Index new project
robomonkey index --repo /path/to/project --name projectname

# Generate embeddings
python scripts/embed_repo_direct.py projectname robomonkey_projectname

# Check database status
docker ps

# Stop database
docker-compose down

# Start database
docker-compose up -d

# View database logs
docker logs robomonkey-postgres
```

---

**🎉 Congratulations!** You've set up RoboMonkey MCP and can now search your code using AI!

**Next:** Read [USER_GUIDE.md](USER_GUIDE.md) for advanced usage and troubleshooting.
