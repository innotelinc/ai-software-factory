#!/usr/bin/env bash
# The escalation channel. Reads the message on stdin and tries to actually REACH a
# person, rather than writing to a file and calling that a notification.
#
# `FACTORY_NOTIFY_CMD` points here by default. Configure ONE of these and it works:
#
#   FACTORY_NTFY_TOPIC=my-factory       -> https://ntfy.sh/my-factory (phone push, free)
#   FACTORY_WEBHOOK_URL=https://...     -> any JSON {"text": ...} endpoint, Slack included
#   (nothing)                           -> desktop notification, then the log file
#
# WHY IT EXISTS. The default used to be `tee -a .factory/escalations.log`, so every
# escalation and every watchdog halt was written to a FILE NOBODY OPENS -- the failure
# this project names in its own docs, sitting inside the escalation path. It matters
# most in the case the whole system is built for: nobody watching. The watchdog halts on
# its own, but a human still has to LEARN that it halted, or the factory sits stopped
# overnight looking exactly like one with nothing to do.
#
# ORDER: durable record first and unconditionally, then the loudest channel available.
#
# EVERY FAILURE IS ANNOUNCED ON STDOUT. An earlier version returned 0 whether or not the
# send succeeded, so a channel that could not be posted to looked exactly like a
# delivered notification -- the silent-failure pattern this whole system exists to stamp
# out, reproduced inside the alarm. `NOTIFY_*_FAILED` and `NOTIFY_UNDELIVERED` are
# matched by `.factory/monitor.py`, so a notification path that breaks is itself an
# event. An alarm nobody checks is the same problem one layer up.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGFILE="$HERE/escalations.log"

MESSAGE="$(cat)"
[ -z "$MESSAGE" ] && exit 0

# 1. The durable copy. Unconditional, and FIRST, because everything below can fail.
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MESSAGE" >> "$LOGFILE" 2>/dev/null

delivered=""

# `--fail` IS LOAD-BEARING. Without it curl exits 0 on a 4xx or 5xx, so a message
# the server REJECTED is reported as delivered -- a false success inside the alarm,
# which is the one place it costs the most. Measured: `curl -sS` exits 0 against a
# URL that returns an error, `curl -sS --fail` exits 22.
#
# 2. ntfy.sh -- the lowest-friction way to get this on a phone. No account, no app
#    registration; pick an unguessable topic name and subscribe to it.
if [ -z "$delivered" ] && [ -n "${FACTORY_NTFY_TOPIC:-}" ]; then
  if command -v curl >/dev/null 2>&1; then
    if curl -sS --fail -m 20 -d "$MESSAGE" "https://ntfy.sh/${FACTORY_NTFY_TOPIC}" >/dev/null 2>&1; then
      delivered="ntfy"
    else
      echo "NOTIFY_NTFY_FAILED topic=${FACTORY_NTFY_TOPIC}"
    fi
  else
    echo "NOTIFY_NTFY_FAILED curl is not installed"
  fi
fi

# 3. A webhook. Slack incoming-webhooks take exactly this shape, and so do most others.
if [ -z "$delivered" ] && [ -n "${FACTORY_WEBHOOK_URL:-}" ]; then
  if command -v curl >/dev/null 2>&1; then
    # Quote-escaped so a message containing " or \ cannot produce invalid JSON, which
    # would fail in a way that looks like the endpoint rejecting the alert.
    _payload=$(printf '%s' "$MESSAGE" | sed 's/\\/\\\\/g; s/"/\\"/g')
    if curl -sS --fail -m 20 -H 'Content-Type: application/json' \
         -d "{\"text\": \"$_payload\"}" "$FACTORY_WEBHOOK_URL" >/dev/null 2>&1; then
      delivered="webhook"
    else
      echo "NOTIFY_WEBHOOK_FAILED"
    fi
  else
    echo "NOTIFY_WEBHOOK_FAILED curl is not installed"
  fi
fi

# 4. The desktop, which works whenever somebody is actually at the machine.
if [ -z "$delivered" ]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin)
      if osascript -e "display notification \"$MESSAGE\" with title \"Software factory\"" >/dev/null 2>&1; then
        delivered="desktop"
      fi ;;
    Linux)
      if command -v notify-send >/dev/null 2>&1 && notify-send "Software factory" "$MESSAGE" >/dev/null 2>&1; then
        delivered="desktop"
      fi ;;
    *)
      # Windows, including Git Bash and MSYS.
      if command -v powershell >/dev/null 2>&1; then
        _ps="[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null"
        if powershell -NoProfile -Command "$_ps" >/dev/null 2>&1; then
          delivered="desktop"
        fi
      fi ;;
  esac
  [ -z "$delivered" ] && echo "NOTIFY_DESKTOP_FAILED"
fi

if [ -z "$delivered" ]; then
  # NOT an error exit: losing the ping must not also fail the escalation that was trying
  # to send it. But it is said out loud, every time, so "nobody was told" can never be
  # mistaken for "nothing happened".
  echo "NOTIFY_UNDELIVERED - recorded in $LOGFILE and nowhere else. Set FACTORY_NTFY_TOPIC"
  echo "                     or FACTORY_WEBHOOK_URL so escalations reach a person."
else
  echo "NOTIFIED via $delivered"
fi
exit 0
