#!/bin/bash
# Run performance tests and generate report

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Performance Testing Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo -e "${RED}Error: Virtual environment not found${NC}"
    exit 1
fi

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${YELLOW}Installing pytest...${NC}"
    pip install pytest pytest-asyncio
fi

# Create reports directory
mkdir -p reports

# Run performance tests
echo -e "${GREEN}Running performance tests...${NC}"
echo ""

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="reports/performance_${TIMESTAMP}.txt"

pytest tests/test_performance.py -v -s --tb=short 2>&1 | tee "$REPORT_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo -e "${BLUE}========================================${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All performance tests passed${NC}"
else
    echo -e "${RED}✗ Some performance tests failed${NC}"
fi
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Report saved to: ${BLUE}$REPORT_FILE${NC}"
echo ""

exit $EXIT_CODE
