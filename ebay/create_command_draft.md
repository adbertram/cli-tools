This workflow describes how to create a new custom command for the agent.

1.  **Determine the Command Name and Purpose**:
    *   Ask the user for the name of the command (e.g., `test-command`) and what it should do.

2.  **Determine the Target Location**:
    *   Check the current working directory.
    *   **IF** the project is located in `/Users/adam/Desktop/Devolutions/RDM` or any of its subfolders:
        *   Ask the user: "Is this a **Team** command or a **Personal** command?"
        *   **If Team Command**:
            *   Set the target directory to `.claude/commands`.
        *   **If Personal Command**:
            *   Set the target directory to `.claude/commands/personal`.
            *   *Note*: You will need to create a symlink later.
    *   **ELSE** (for all other projects):
        *   Set the target directory to `.claude/commands`.

3.  **Create the Command File**:
    *   Create a new file in the *Target Directory* with the name `[command-name].md`.
    *   Write the instructions for the command into this file based on the user's description.

4.  **Handle Personal Command Linking (If applicable)**:
    *   **IF** this was a **Personal Command** (created in `.claude/commands/personal`):
        *   Create a symbolic link in `.claude/commands` that points to the new file in `.claude/commands/personal`.
        *   Example execution: `ln -s .claude/commands/personal/[command-name].md .claude/commands/[command-name].md` (Adjust paths as necessary for relative vs absolute).

5.  **Final Confirmation**:
    *   Inform the user the command has been created and is ready to use.
