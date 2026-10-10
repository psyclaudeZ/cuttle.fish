# cuttle snapshots the parent history and starts a private child fish.
# The child loads normal configuration, imports the snapshot into memory,
# and marks its prompt with 🥷. Inherited and new commands remain usable
# in the child, but new commands never merge into the parent history.
# Exiting discards the child history and returns to the original parent shell.
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

    # NUL-delimited, oldest-first entries preserve multiline commands and recall order.
    # fd 9 carries history; /dev/tty keeps the child interactive.
    # Clear the inherited namespace to prevent named history from enabling saves.
    builtin history search --null --reverse | command /bin/sh -c \
        'fish_history= exec "$@" 9<&0 </dev/tty' cuttle "$fish_executable" \
        --private --interactive --init-command '
            if test -n "$fish_history"
                printf "cuttle: startup configuration changed fish_history; refusing to import history\n" >&2
                exec /bin/sh -c "exit 1"
            end
            set -gx fish_history ""
            # Disable the read limit for large history snapshots.
            begin
                set -l fish_read_limit 0
                set -gu __cuttle_history (command /bin/cat <&9 | builtin string split0)
            end
            functions --copy fish_prompt __cuttle_original_prompt
            function fish_prompt
                # Capture the prompt first to preserve status/pipestatus and newlines.
                set -l original_prompt (__cuttle_original_prompt $argv | builtin string collect --allow-empty --no-trim-newlines)
                set -l ansi "\e\[[0-?]*[ -/]*[@-~]"
                set -l username "((?:$ansi)*)[[:alnum:]_.-]+((?:$ansi)*)(?=@)"
                if builtin string match --quiet --regex -- "^$username" "$original_prompt"
                    # The sentinel limits replacement to the first line; piping preserves newlines.
                    printf "\036%s" "$original_prompt" | builtin string replace --regex -- "^\x1e$username" "\$1🥷\$2"
                else
                    printf "%s%s" "🥷 " "$original_prompt"
                end
            end
            # Private history exists only after the interactive reader starts.
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
