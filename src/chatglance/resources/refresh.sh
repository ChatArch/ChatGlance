#!/bin/sh
set -eu
exec chatglance refresh --no-restart "$@"
