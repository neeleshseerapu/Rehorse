#!/usr/bin/env python3
"""PreToolUse hook for Bash: the real branch is untouchable while a task rehearses.

Denies (with the way out in the reason): git merge/rebase/pull/push/checkout/switch, reset --hard, branch delete/move,
worktree changes; git commit outside the worktree; rm -rf on the repo root, its parents, .rehorse/ or a worktree root;
--no-verify or core.hooksPath. Git denials lift when REHORSE_MERGE_TOKEN (env, or `VAR=... git ...` in the command)
matches state["merge_token"], which only merge.py sets. This is a token check, not a shell parser: it splits on
&&, ||, ;, |, newlines, parentheses and backticks and recurses into `-c "..."` / `eval "..."` strings.
"""
import json
import os
import re
import shlex
import sys

import state
import testcmd
import worktree

BRANCH_CMDS = {"merge", "rebase", "pull", "push", "checkout", "switch"}
GIT_OPT_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def segments(command):
    """Simple commands of a shell line, each as a token list. shlex keeps quoted strings whole and, with
    punctuation_chars, returns operators (&&, ||, ;, |, parentheses) as their own tokens, which split the segments."""
    lex = shlex.shlex(re.sub(r"[`\n]", " ; ", command), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:  # unbalanced quotes: best effort on whitespace
        tokens = command.split()
    out, cur = [], []
    for tok in tokens + [";"]:
        if not re.fullmatch(r"[();<>|&]+", tok):
            cur.append(tok)
            continue
        while cur and re.match(r"^\w+=", cur[0]):  # leading VAR=value assignments
            cur.pop(0)
        if cur:
            out.append(cur)
            out += [t for j, w in enumerate(cur) if j and cur[j - 1] in ("-c", "eval") for t in segments(w)]
        cur = []
    return out


def git_call(toks, cwd):
    """(subcommand, args, cwd) for a git invocation, honouring -C; None for anything else."""
    if toks[0] != "git":
        return None
    i = 1
    while i < len(toks) and toks[i].startswith("-"):
        if toks[i] == "-C" and i + 1 < len(toks):
            cwd = os.path.join(cwd, os.path.expanduser(toks[i + 1]))
        i += 2 if toks[i] in GIT_OPT_WITH_ARG else 1
    return (toks[i] if i < len(toks) else "", toks[i + 1:], cwd)


def protected(p, root):
    """Repo root, any parent of it, .rehorse/ itself, worktrees/, a worktree root: yes. Files inside a worktree: no."""
    rehorse = os.path.join(root, ".rehorse")
    if p == root or root.startswith(p + os.sep):
        return True
    if not (p == rehorse or p.startswith(rehorse + os.sep)):
        return False
    inside = os.path.relpath(p, os.path.join(rehorse, "worktrees")).split(os.sep)
    return len(inside) < 2 or inside[0].startswith("..")


def check(command, cwd, root, task, token_ok):
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    root = os.path.realpath(root)
    cwd = os.path.realpath(testcmd.effective_cwd(command, cwd))
    tid = task["id"]
    for toks in segments(command):
        if toks[0] == "rm" and any(re.match(r"^-[a-zA-Z]*[rR]", t) or t == "--recursive" for t in toks[1:]):
            for target in (t for t in toks[1:] if not t.startswith("-")):
                p = os.path.realpath(os.path.join(cwd, os.path.expanduser(target.rstrip("*").rstrip("/") or ".")))
                if protected(p, root):
                    return ("`rm -rf` on the repo root or .rehorse/ is denied. To drop the rehearsal, run "
                            "/rehorse:discard %s; inside %s you may delete build outputs freely." % (tid, wt))
        call = git_call(toks, cwd)
        if not call or token_ok:
            continue
        sub, args, gcwd = call
        if "--no-verify" in args or (sub == "commit" and "-n" in args) or any("core.hooksPath" in t for t in toks):
            return "`--no-verify` / hooksPath overrides are denied. Run the command without it and fix what the git hook reports."
        if (sub in BRANCH_CMDS or (sub == "reset" and "--hard" in args) or (sub == "worktree" and args[:1] != ["list"])
                or (sub == "branch" and any(re.match(r"^-(-delete|-move|-force|[dDmMf]+)$", a) for a in args))):
            return ("`git %s` is denied while task %s is rehearsing: only /rehorse:merge and /rehorse:discard, run by the "
                    "user, touch the real branch. Work inside %s and commit there; to undo a file use `git restore <file>`."
                    % (sub, tid, wt))
        if sub == "commit" and not worktree.contains(wt, os.path.realpath(gcwd)):
            return "`git commit` outside the worktree is denied. Run `cd %s && git commit ...` instead." % wt
    return None


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task:
        return 0
    command = (hook.get("tool_input") or {}).get("command") or ""
    token = s.get("merge_token")
    token_ok = bool(token) and (os.environ.get("REHORSE_MERGE_TOKEN") == token or "REHORSE_MERGE_TOKEN=%s " % token in command)
    reason = check(command, hook.get("cwd") or os.getcwd(), root, task, token_ok)
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": "REHORSE: " + reason}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
