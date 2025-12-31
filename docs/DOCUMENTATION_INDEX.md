# RoboMonkey MCP Documentation Index

Welcome to RoboMonkey MCP! This index helps you find the right documentation for your needs.

---

## 🚀 Just Starting? Start Here!

### [QUICKSTART.md](QUICKSTART.md)
**For complete beginners** - Step-by-step guide assuming no prior knowledge of Docker, AI, or command-line tools.

**Read this if:**
- You've never used Docker before
- You're new to AI coding tools
- You want simple copy-paste instructions
- You just want to get it working quickly

**Time to complete:** 30-45 minutes

---

## 📦 Setting Up on a Server

### [INSTALL.md](INSTALL.md)
**Complete installation guide** for setting up RoboMonkey MCP on a new server.

**Covers:**
- ✅ **A. CLI Setup** - Installing and configuring the command-line interface
- ✅ **B. Daemon Setup** - Running background workers for automatic processing
- ✅ **C. MCP Server Setup** - Enabling IDE integration
- ✅ **D. IDE Integration** - Connecting to Claude Desktop, Cline, Cursor, VS Code

**Read this if:**
- You're deploying to a production server
- You need the daemon for automatic updates
- You want to integrate with multiple IDEs
- You need systemd service configuration

**Time to complete:** 1-2 hours

---

## 📖 Using RoboMonkey MCP

### [USER_GUIDE.md](USER_GUIDE.md)
**Comprehensive usage guide** with examples and troubleshooting.

**Covers:**
- ✅ **E. Usage Examples** - How to use RoboMonkey MCP and test if it's working
- ✅ **F. Clearing Data** - How to reset and start over
- ✅ **G. Troubleshooting** - Where logs are, how to debug issues

**Read this if:**
- You have RoboMonkey installed and want to use it effectively
- You're getting errors and need to debug
- You want advanced usage patterns
- You need to clear data or reset

**Time to read:** 20-30 minutes

---

## 🎯 Quick Reference

### Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `.env` | Main configuration | `robomonkey-mcp/.env` |
| `.env.example` | Configuration template | `robomonkey-mcp/.env.example` |
| `docker-compose.yml` | Database setup | `robomonkey-mcp/docker-compose.yml` |
| `claude_desktop_config.json` | Claude Desktop integration | `~/Library/Application Support/Claude/` (Mac) |
| `mcp-servers.json` | Claude Code integration | `~/.config/claude-code/` |

### Key Commands

```bash
# Database
robomonkey db init          # Initialize database
robomonkey db ping          # Check connection

# Indexing
robomonkey index --repo /path/to/repo --name myrepo
robomonkey status --name myrepo
robomonkey repo ls

# Embeddings
python scripts/embed_repo_direct.py myrepo robomonkey_myrepo

# Daemon
robomonkey daemon run       # Start daemon
systemctl status robomonkey-daemon  # Check daemon status

# Docker
docker-compose up -d       # Start database
docker-compose down        # Stop database
docker ps                  # List running containers
docker logs robomonkey-postgres  # View database logs
```

### Common File Paths

**Mac/Linux:**
- RoboMonkey: `~/robomonkey-mcp/`
- Virtual environment: `~/robomonkey-mcp/.venv/`
- Python: `~/robomonkey-mcp/.venv/bin/python`
- Claude config: `~/Library/Application Support/Claude/`

**Windows:**
- RoboMonkey: `C:\Users\YourName\robomonkey-mcp\`
- Virtual environment: `C:\Users\YourName\robomonkey-mcp\.venv\`
- Python: `C:\Users\YourName\robomonkey-mcp\.venv\Scripts\python.exe`
- Claude config: `%APPDATA%\Claude\`

---

## 🔧 Operational Guides

### [RUNBOOK.md](RUNBOOK.md)
**Day-to-day operations** - Control schema, daemon architecture, and runtime procedures.

**Read this if:**
- You're managing a production deployment
- You need to understand the daemon architecture
- You want to monitor system health

### [TODO.md](TODO.md)
**Development roadmap** - Current phase, completed features, and upcoming work.

**Read this if:**
- You're contributing to development
- You want to know what features are coming
- You're debugging and need to understand implementation status

---

## ❓ FAQ - Which Guide Do I Need?

### "I've never done this before and need hand-holding"
→ Start with [QUICKSTART.md](QUICKSTART.md)

### "I need to deploy this on a production server"
→ Follow [INSTALL.md](INSTALL.md)

### "I have it installed, how do I use it?"
→ Read [USER_GUIDE.md](USER_GUIDE.md)

### "Something's broken, how do I fix it?"
→ See [USER_GUIDE.md - Troubleshooting](USER_GUIDE.md#g-troubleshooting)

### "I want to integrate with my IDE"
→ See [INSTALL.md - IDE Integration](INSTALL.md#d-ide-integration)

### "How do I clear everything and start over?"
→ See [USER_GUIDE.md - Clearing Data](USER_GUIDE.md#f-clearing-data-and-starting-over)

### "Where are the logs?"
→ See [USER_GUIDE.md - Logs](USER_GUIDE.md#where-are-the-logs)

### "I'm a developer working on RoboMonkey"
→ Check [CLAUDE.md](CLAUDE.md) and [TODO.md](TODO.md)

---

## 📊 Documentation Status

| Document | Status | Last Updated | Completeness |
|----------|--------|--------------|--------------|
| QUICKSTART.md | ✅ Complete | 2025-12-31 | 100% |
| INSTALL.md | ✅ Complete | 2025-12-31 | 100% |
| USER_GUIDE.md | ✅ Complete | 2025-12-31 | 100% |
| RUNBOOK.md | ✅ Complete | 2025-12-30 | 95% |
| CLAUDE.md | ✅ Complete | 2025-12-30 | 100% |
| TODO.md | 🔄 In Progress | 2025-12-30 | 90% |

---

## 🎓 Learning Path

### Beginner Path (0-2 hours)
1. Read [QUICKSTART.md](QUICKSTART.md) - 30 min
2. Follow all steps to get it working - 45-60 min
3. Try the test examples - 15 min
4. Skim [USER_GUIDE.md](USER_GUIDE.md) examples - 15 min

### Intermediate Path (2-4 hours)
1. Complete Beginner Path
2. Read [INSTALL.md](INSTALL.md) sections A-C - 45 min
3. Set up daemon for automatic processing - 30 min
4. Read [USER_GUIDE.md](USER_GUIDE.md) usage patterns - 30 min
5. Experiment with advanced searches - 30 min

### Advanced Path (4-8 hours)
1. Complete Intermediate Path
2. Read all of [INSTALL.md](INSTALL.md) - 1 hour
3. Set up IDE integration - 30 min
4. Read [RUNBOOK.md](RUNBOOK.md) - 1 hour
5. Study [USER_GUIDE.md](USER_GUIDE.md) troubleshooting - 45 min
6. Review [CLAUDE.md](CLAUDE.md) for architecture - 45 min

---

## 🆘 Getting Help

### Before Asking for Help

1. **Check if your issue is in troubleshooting:**
   - [USER_GUIDE.md - Troubleshooting](USER_GUIDE.md#g-troubleshooting)

2. **Gather diagnostic information:**
   ```bash
   # Check database
   robomonkey db ping
   
   # Check Docker
   docker ps
   
   # Check virtual environment
   which python
   
   # Check Ollama
   ollama list
   ```

3. **Check the logs:**
   ```bash
   # Database
   docker logs robomonkey-postgres
   
   # Daemon (if using systemd)
   sudo journalctl -u robomonkey-daemon -n 50
   ```

### Where to Get Help

- **GitHub Issues:** Report bugs or request features
- **Discussions:** Ask questions and share tips
- **Documentation Issues:** Report errors in docs

### What to Include in Bug Reports

1. What command you ran
2. Full error message
3. Output of diagnostic commands above
4. Your operating system
5. Relevant section of logs

---

## 🔄 Keeping Documentation Up to Date

This documentation is current as of **December 31, 2025**.

If you find errors or outdated information:
1. Check the `Last Updated` date above
2. Check GitHub for newer versions
3. Report issues with specific file and section references

---

## 📝 Contributing to Documentation

Improvements welcome! When contributing:

1. **QUICKSTART.md** - Keep it beginner-friendly, no jargon
2. **INSTALL.md** - Be comprehensive, include all options
3. **USER_GUIDE.md** - Add examples and real error messages
4. **RUNBOOK.md** - Focus on production operations

---

**Happy coding with RoboMonkey MCP!** 🚀

Start with [QUICKSTART.md](QUICKSTART.md) if you're new, or jump to [INSTALL.md](INSTALL.md) for server deployment.
