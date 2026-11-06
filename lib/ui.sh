# Sourced by start.sh: messaging utilities - sober design
msg() { echo -e "\033[0;37m${1}\033[0m"; }
msg_detail() { echo -e "\033[0;90m  ${1}\033[0m"; }
msg_warn() { echo -e "\033[0;90m${1}\033[0m"; }
