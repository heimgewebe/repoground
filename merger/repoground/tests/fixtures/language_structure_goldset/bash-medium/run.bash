#!/usr/bin/env bash
source lib/helpers.bash
build() {
  helper
}
test_all() {
  helper
}
release() {
  build
  test_all
}
