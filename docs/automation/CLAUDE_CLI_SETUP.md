# Claude Code CLI Setup for AI Categorization

## Overview

The AI categorization system can use **Claude Code CLI** (free, uses your subscription) instead of the Anthropic API (requires separate credits).

## Priority Order

1. **Claude Code CLI** (if available) - FREE ✅
2. **Anthropic API** (if API key provided) - ~$0.09/month

## One-Time CLI Setup

### Test Claude Code CLI

Before using it in automation, test it manually:

```bash
# Simple test
claude -p "Categorize this: Netflix €9.99"
```

**First time?** You may need to:
- Approve CLI access interactively
- Initialize session
- This only happens once

### Verify CLI Works

```bash
# Test with JSON output
claude -p "Return JSON: {\"test\": \"ok\"}" --output-format json --model haiku
```

You should see JSON output like:
```json
{
  "type": "result",
  "subtype": "success",
  "result": "{\"test\": \"ok\"}",
  ...
}
```

## Using in Finance Automation

Once CLI is tested manually:

```python
# In config_settings.py
AI_CATEGORIZATION_ENABLED = True
# No CLAUDE_API_KEY needed - will auto-use CLI!
```

The system will:
1. Detect Claude Code CLI
2. Use it automatically (free)
3. Fall back to API only if CLI unavailable

## Troubleshooting

### "Claude Code CLI timeout"

**Cause**: First-time use needs interactive approval

**Fix**:
```bash
# Run manually once
claude -p "test"
# Approve any prompts
# Then try automation again
```

### "Command 'claude' not found"

**Cause**: Claude Code CLI not installed

**Fix**: Install Claude Code from https://claude.com/code

**Alternative**: Use API instead:
```bash
export CLAUDE_API_KEY="sk-ant-..."
```

### CLI Works Manually But Not in Script

**Cause**: Environment or permissions issue

**Debug**:
```bash
# Check which claude
which claude

# Test as subprocess
python3 << 'EOF'
import subprocess
result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
print(result.stdout)
EOF
```

## Benefits of CLI

✅ **Free** - Uses your Claude Code subscription
✅ **No API setup** - No separate account/credits needed
✅ **Same models** - Haiku, Sonnet, Opus available
✅ **Automatic fallback** - Switches to API if CLI unavailable

## When to Use API Instead

Use Anthropic API if:
- CLI not available on server
- Running in Docker/container without CLI
- Need programmatic access without CLI installation
- Prefer API billing model

## Cost Comparison

| Method | Cost | Setup |
|--------|------|-------|
| **Claude Code CLI** | FREE (included in subscription) | Test manually once |
| **Anthropic API** | ~$0.09/month | Get API key + credits |

---

**Recommendation**: Try CLI first (free), use API as fallback if needed.
