#!/bin/bash
source "$LIB_ROOT/lib.sh"
run() {
  eval "$ACTION"
  result=$(dynamic_command)
}
