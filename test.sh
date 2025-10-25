#!/bin/bash

# Test script for container build and start scripts
# Tests Podman-only (Docker support removed)

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
    echo "  Cleaning up test resources..."

    # Stop and remove test container
    podman stop $TEST_CONTAINER_NAME 2>/dev/null || true
    podman rm $TEST_CONTAINER_NAME 2>/dev/null || true

    # Remove test image
    podman rmi $TEST_IMAGE_NAME:latest 2>/dev/null || true
}

# Function to test Podman
test_podman() {
    echo ""
    echo "Testing with Podman..."
    echo "======================"

    # Check if Podman is available
    if ! command -v podman &> /dev/null; then
        print_test "Podman is installed" "FAIL"
        echo "  ERROR: Podman is not installed"
        return 1
    fi

    print_test "Podman is installed" "PASS"

    # Clean up any existing test resources
    cleanup

    # Test 1: Build with Podman
    echo ""
    echo "Test 1: Building image with Podman (this may take a few minutes...)"
    # Don't use --reset to avoid full rebuild, just build if image doesn't exist
    if ./build.sh --name "$TEST_IMAGE_NAME"; then
        print_test "Build with Podman" "PASS"
    else
        print_test "Build with Podman" "FAIL"
        echo "  Error: Build failed"
        return
    fi

    # Test 2: Check if image exists
    if [ "$(podman images -q $TEST_IMAGE_NAME 2>/dev/null)" != "" ]; then
        print_test "Image created successfully" "PASS"
    else
        print_test "Image created successfully" "FAIL"
        return
    fi

    # Test 3: Start container with custom name
    echo ""
    echo "Test 2: Starting container with custom name"
    # Create container directly without using start.sh to avoid interactive shell issues
    if podman run -d --name $TEST_CONTAINER_NAME $TEST_IMAGE_NAME tail -f /dev/null >/dev/null 2>&1; then
        print_test "Container started with custom name" "PASS"
    else
        print_test "Container started with custom name" "FAIL"
        return
    fi

    # Test 4: Container is running
    if [ "$(podman ps -q -f name=$TEST_CONTAINER_NAME)" ]; then
        print_test "Container is running" "PASS"
    else
        print_test "Container is running" "FAIL"
    fi

    # Test 5: Test reset functionality
    echo ""
    echo "Test 3: Testing reset functionality"
    # Reset should complete without needing interactive mode
    if ./start.sh --image "$TEST_IMAGE_NAME" --name "$TEST_CONTAINER_NAME" --reset --no-shell >/dev/null 2>&1; then
        print_test "Reset functionality works" "PASS"
    else
        print_test "Reset functionality works" "FAIL"
    fi

    # Clean up after tests
    echo ""
    cleanup

    # Verify cleanup
    if [ "$(podman ps -a -q -f name=$TEST_CONTAINER_NAME)" = "" ] && \
       [ "$(podman images -q $TEST_IMAGE_NAME 2>/dev/null)" = "" ]; then
        print_test "Cleanup successful" "PASS"
    else
        print_test "Cleanup successful" "FAIL"
    fi
}

# Main test execution
echo "Podman Container Test Suite"
echo "==========================="

# Test Podman
test_podman

# Final report
echo ""
echo "==========================="
if [ $TEST_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi