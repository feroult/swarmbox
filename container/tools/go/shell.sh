# go (design 6.12). Sourced by every interactive shell (bash and zsh). Go's own defaults, now under the home instead of /opt/go:
# GOPATH=$HOME/go and GOCACHE=$HOME/.cache/go-build, and $GOPATH/bin on PATH (once). A value the user already exported is kept.
# Nothing is created here: Go makes the directories when it needs them.
export GOPATH="${GOPATH:-$HOME/go}"
export GOCACHE="${GOCACHE:-$HOME/.cache/go-build}"
case ":$PATH:" in
    *":$GOPATH/bin:"*) ;;
    *) PATH="$PATH:$GOPATH/bin" ;;
esac
export PATH
