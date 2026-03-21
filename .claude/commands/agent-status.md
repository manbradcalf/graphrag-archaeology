Check the status of all background agents by reading their output files.

1. List all task output files in `/private/tmp/claude-501/-Users-biz-code-graphrag-samples-archaeology/` (recursively find `*.output` files)
2. For each output file, read the last 20 lines to determine if the task is completed or still running
3. Report results in a markdown table with these columns:

| Agent | Status | Summary |
|-------|--------|---------|

- **Agent**: the agent description/name (parse from the output file content)
- **Status**: Running, Completed, or Failed
- **Summary**: brief one-line summary of results (if completed) or current activity (if running)

If no output files are found, report "No background agents found for this session."
