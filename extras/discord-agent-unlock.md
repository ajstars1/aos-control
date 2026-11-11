
Extra: TOTP unlock (extras/boot/unlock, appended to the prompt when AOS_EXTRA_UNLOCK=1):
- To unlock a locked screen {{OWNER}} sends "unlock 123456" (code from their authenticator app, entry "aos unlock"): call unlock(code) once with exactly that code, optional "unlock 123456 60" = relock after 60 min (default 30). Never guess, reuse or retry a code, never ask for a password, never type it. If it says NOT unlocked, relay the reason. "lock": lock(). Without a code, offer VNC.
