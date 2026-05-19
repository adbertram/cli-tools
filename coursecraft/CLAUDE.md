# CourseCraft CLI - Claude Instructions

## Overview
The `coursecraft` CLI manages CourseCraft course content. It replicates functionality from the bash scripts in `~/Dropbox/GitRepos/Agents/CourseCraft/scripts/` but provides a cleaner Python interface.

## Key Design Decisions
1. **Wraps database operations** - This CLI provides a simplified interface for course content management
2. **No authentication required** - Uses the existing backend authentication
3. **Supports nested creation** - Can create courses with modules and clips in one command
4. **Course slug resolution** - Modules can reference courses by Course ID slug or record ID

## Available Commands
- `coursecraft courses create` - Create course records with nested modules/clips
- `coursecraft modules create` - Create module records with nested clips
- `coursecraft clips create` - Create clip records (single or batch mode)
- `coursecraft demos create` - Create demo records (single or batch mode)
- `coursecraft slides create` - Create slide records (single or batch mode)

## Architecture
- **client.py** - Wraps airtable CLI commands, provides `create_record()`, `list_records()`, `resolve_course_id()`
- **commands/** - Each resource (courses, modules, clips, demos, slides) has its own command module
- **Nested creation** - Courses can create modules via JSON, modules can create clips, etc.
- **Output** - Always outputs record ID(s) for scripting (to stdout), with status messages to stderr

## Configuration
Configuration stored in `.env` file (see package documentation for required variables)
