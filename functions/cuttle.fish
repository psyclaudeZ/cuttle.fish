# How cuttle works:
# 1. Search the parent reader's visible history, including in-memory entries,
#    without merging other shells. Emit oldest-first, NUL-delimited records so
#    multiline commands and literal shell syntax remain data.
# 2. A fixed sh exec wrapper moves the pipe to fd 9 and opens /dev/tty as stdin.
#    The transfer uses neither argv/environment data nor regular temporary files.
#    Clear fish_history only in the child's environment, keeping the parent intact.
# 3. Start fish --private with normal configuration. Reject a nonempty history
#    namespace, then capture the pipe in an unexported child variable. cat feeds
#    fd 9 to string split0; the scoped read-limit override permits large snapshots.
# 4. Replace the child's prompt_login helper with 🥷@dev. The configured
#    fish_prompt stays intact, including its status handling and other details.
#    This changes the identity segment in prompts that call prompt_login.
# 5. Import once at the first fish_prompt event, after the private interactive
#    reader exists. history append accepts each record literally, in order.
#    The handler unregisters itself before importing, then erases the snapshot.
# The parent waits for the child and returns its exit status. Child history and
# prompt changes disappear with that process; nothing is merged into the parent.
function cuttle --description 'Start a private fish with inherited history'
    if test (count $argv) -ne 0
        printf 'Usage: cuttle\n' >&2
        return 2
    end
    set -l fish_executable (status fish-path)
    if not status is-interactive; or not isatty stdin
        printf 'cuttle: an interactive terminal is required\n' >&2
        return 2
    end
    set -l major (string split . -- $version)[1]
    if test "$major" -lt 4
        printf 'cuttle: fish 4.0 or newer is required\n' >&2
        return 2
    end

    # The builtin searches this process's visible history without merging.
    # Oldest first: append makes the last imported entry the newest one.
    # fd 9 carries NUL-delimited data; stdin stays on the controlling terminal.
    # Apply redirections after fish has connected the pipeline's stdin, and
    # prevent an exported parent namespace from reaching startup configuration.
    builtin history search --null --reverse | command /bin/sh -c \
        'fish_history= exec "$@" 9<&0 </dev/tty' cuttle "$fish_executable" \
        --private --interactive --init-command '
            if test -n "$fish_history"
                printf "cuttle: startup configuration changed fish_history; refusing to import history\n" >&2
                exec /bin/sh -c "exit 1"
            end
            set -gx fish_history ""
            # Capture now: prompt event handlers do not have the pipe as stdin.
            begin
                set -l fish_read_limit 0
                set -gu __cuttle_history (command /bin/cat <&9 | builtin string split0)
            end
            function prompt_login
                printf "%s" "🥷@dev"
            end
            # An unnamed private history belongs to the interactive reader.
            # Seed at its first prompt, after that reader has been created.
            function __cuttle_seed_history --on-event fish_prompt
                functions --erase __cuttle_seed_history
                if test -n "$fish_history"
                    printf "cuttle: fish_history changed before import\n" >&2
                    exec /bin/sh -c "exit 1"
                end
                for entry in $__cuttle_history
                    builtin history append -- "$entry"; or exec /bin/sh -c "exit 1"
                end
                set -e __cuttle_history
            end
        '
    return $pipestatus[-1]
end
