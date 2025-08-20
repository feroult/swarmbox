#!/bin/bash

# Test script for container build and start scripts
# Tests both Docker and Podman (if available)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test configuration
TEST_IMAGE_NAME="swarmbox-test"
TEST_CONTAINER_NAME="swarmbox-test-container"
TEST_FAILED=0

# Function to print test status
print_test() {
    local test_name="$1"
    local status="$2"
    
    if [ "$status" = "PASS" ]; then
        echo -e "${GREEN}✓${NC} $test_name"
    elif [ "$status" = "SKIP" ]; then
        echo -e "${YELLOW}⚠${NC} $test_name (SKIPPED)"
    else
        echo -e "${RED}✗${NC} $test_name"
        TEST_FAILED=1
    fi
}

# Function to cleanup test resources
cleanup() {
    local runtime="$1"
    echo "  Cleaning up test resources for $runtime..."
    
    # Stop and remove test container
    $runtime stop $TEST_CONTAINER_NAME 2>/dev/null || true
    $runtime rm $TEST_CONTAINER_NAME 2>/dev/null || true
    
    # Remove test image
    $runtime rmi $TEST_IMAGE_NAME:latest 2>/dev/null || true
}

# Function to test runtime
test_runtime() {
    local runtime="$1"
    
    echo ""
    echo "Testing with $runtime..."
    echo "========================"
    
    # Check if runtime is available
    if ! command_exists "$runtime"; then
        print_test "$runtime is installed" "SKIP"
        echo "  $runtime is not installed, skipping tests"
        return
    fi
    
    print_test "$runtime is installed" "PASS"
    
    # Clean up any existing test resources
    cleanup "$runtime"
    
    # Test 1: Build with runtime
    echo ""
    echo "Test 1: Building image with $runtime (this may take a few minutes...)"
    # Don't use --reset to avoid full rebuild, just build if image doesn't exist
    if ./build.sh --runtime "$runtime" --name "$TEST_IMAGE_NAME"; then
        print_test "Build with $runtime" "PASS"
    else
        print_test "Build with $runtime" "FAIL"
        echo "  Error: Build failed"
        return
    fi
    
    # Test 2: Check if image exists
    if [ "$($runtime images -q $TEST_IMAGE_NAME 2>/dev/null)" != "" ]; then
        print_test "Image created successfully" "PASS"
    else
        print_test "Image created successfully" "FAIL"
        return
    fi
    
    # Test 3: Start container with custom name
    echo ""
    echo "Test 2: Starting container with custom name"
    # Create container directly without using start.sh to avoid interactive shell issues
    if $runtime run -d --name $TEST_CONTAINER_NAME $TEST_IMAGE_NAME tail -f /dev/null >/dev/null 2>&1; then
        print_test "Container started with custom name" "PASS"
    else
        print_test "Container started with custom name" "FAIL"
        return
    fi
    
    # Test 4: Container is running
    if [ "$($runtime ps -q -f name=$TEST_CONTAINER_NAME)" ]; then
        print_test "Container is running" "PASS"
    else
        print_test "Container is running" "FAIL"
    fi
    
    # Test 5: Test reset functionality
    echo ""
    echo "Test 3: Testing reset functionality"
    # Reset should complete without needing interactive mode
    if ./start.sh --runtime "$runtime" --image "$TEST_IMAGE_NAME" --name "$TEST_CONTAINER_NAME" --reset >/dev/null 2>&1; then
        print_test "Reset functionality works" "PASS"
    else
        print_test "Reset functionality works" "FAIL"
    fi
    
    # Clean up after tests
    echo ""
    cleanup "$runtime"
    
    # Verify cleanup
    if [ "$($runtime ps -a -q -f name=$TEST_CONTAINER_NAME)" = "" ] && \
       [ "$($runtime images -q $TEST_IMAGE_NAME 2>/dev/null)" = "" ]; then
        print_test "Cleanup successful" "PASS"
    else
        print_test "Cleanup successful" "FAIL"
    fi
}

# Main test execution
echo "Container Runtime Test Suite"
echo "============================"

# Test Docker
test_runtime "docker"

# Test Podman
test_runtime "podman"

# Final report
echo ""
echo "============================"
if [ $TEST_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi