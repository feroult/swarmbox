#!/bin/bash
# swarmbox-pubkey: the SSH key SwarmBox uses for git over SSH.
#
#   swarmbox-pubkey            create the key if it does not exist, then show the public key and how to authorize it
#   swarmbox-pubkey --ensure   create it if missing and print one short line (what the shell fragment runs in every shell)
#
# The key is ~/.ssh/id_ed25519. The home directory is the workspace folder on the host, so the key survives
# `swarmbox reset`; it is generated once and never overwritten.
SSH_DIR="${SWARMBOX_SSH_DIR:-$HOME/.ssh}"
KEY="$SSH_DIR/id_ed25519"

if [ -r /etc/swarmbox/scripts/messages.sh ]; then
    source /etc/swarmbox/scripts/messages.sh
else
    msg() { echo "$1"; }
    msg_detail() { echo "  $1"; }
    msg_blank() { echo ""; }
fi

created=false
if [ ! -f "$KEY" ]; then
    mkdir -p "$SSH_DIR" && chmod 700 "$SSH_DIR"
    ssh-keygen -q -t ed25519 -N "" -C "swarmbox@$(hostname)" -f "$KEY" || { echo "could not create $KEY" >&2; exit 1; }
    created=true
fi
# the public half is always derivable from the private one
[ -s "$KEY.pub" ] || ssh-keygen -y -f "$KEY" > "$KEY.pub"
fingerprint=$(ssh-keygen -lf "$KEY.pub" | awk '{print $2}')

if [ "$1" = "--ensure" ]; then
    $created && msg_detail "Git SSH key created in $SSH_DIR"
    msg_detail "Git SSH key: $fingerprint (run swarmbox-pubkey to show it)"
    exit 0
fi

msg_blank
msg "SwarmBox SSH public key ($fingerprint):"
msg_blank
cat "$KEY.pub"
msg_blank
msg_detail "To let SwarmBox use a repository, add it there as a deploy key (allow write access to push):"
msg_detail "  GitHub:    https://github.com/<owner>/<repo>/settings/keys/new"
msg_detail "  GitLab:    <repo> > Settings > Repository > Deploy keys"
msg_detail "  Bitbucket: <repo> > Repository settings > Access keys"
msg_detail "A deploy key reaches one repository. Adding it to your account instead gives SwarmBox every repo you can access."
msg_detail "The private key is $KEY (on your machine: .ssh/id_ed25519 in the workspace folder): anything running in SwarmBox can use it."
msg_blank
