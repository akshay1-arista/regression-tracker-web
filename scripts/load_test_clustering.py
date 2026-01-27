#!/usr/bin/env python3
"""
Load testing script for error clustering endpoint.

Tests concurrent requests to the clustering API to verify production
server can handle multiple users.

Usage:
    python scripts/load_test_clustering.py --url http://localhost:8000 --concurrent 10
"""

import argparse
import asyncio
import time
from typing import List, Dict
import httpx
import statistics


async def fetch_clusters(client: httpx.AsyncClient, url: str, session_id: int) -> Dict:
    """Fetch clusters from API and measure response time."""
    start_time = time.time()
    try:
        response = await client.get(url)
        elapsed = time.time() - start_time

        return {
            'session_id': session_id,
            'status_code': response.status_code,
            'elapsed': elapsed,
            'success': response.status_code == 200,
            'error': None
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            'session_id': session_id,
            'status_code': None,
            'elapsed': elapsed,
            'success': False,
            'error': str(e)
        }


async def run_concurrent_requests(base_url: str, endpoint: str, concurrent: int, iterations: int):
    """Run concurrent requests to clustering endpoint."""
    url = f"{base_url}{endpoint}"

    print(f"🔄 Load Testing Error Clustering Endpoint")
    print(f"   URL: {url}")
    print(f"   Concurrent requests: {concurrent}")
    print(f"   Iterations: {iterations}")
    print(f"   Total requests: {concurrent * iterations}")
    print()

    all_results = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for iteration in range(iterations):
            print(f"Iteration {iteration + 1}/{iterations}...")

            # Create concurrent requests
            tasks = [
                fetch_clusters(client, url, session_id=i)
                for i in range(concurrent)
            ]

            # Execute concurrently
            results = await asyncio.gather(*tasks)
            all_results.extend(results)

            # Small delay between iterations
            if iteration < iterations - 1:
                await asyncio.sleep(1)

    return all_results


def analyze_results(results: List[Dict]):
    """Analyze load test results and print statistics."""
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]

    if successful:
        response_times = [r['elapsed'] for r in successful]

        print("\n" + "="*60)
        print("📊 LOAD TEST RESULTS")
        print("="*60)

        print(f"\n✅ Successful Requests: {len(successful)}/{len(results)}")
        print(f"❌ Failed Requests: {len(failed)}/{len(results)}")

        if failed:
            print(f"\n⚠️  Failed Request Details:")
            for r in failed[:5]:  # Show first 5 failures
                print(f"   - Session {r['session_id']}: {r['error'] or 'HTTP ' + str(r['status_code'])}")

        print(f"\n⏱️  Response Time Statistics:")
        print(f"   Min:     {min(response_times):.3f}s")
        print(f"   Max:     {max(response_times):.3f}s")
        print(f"   Mean:    {statistics.mean(response_times):.3f}s")
        print(f"   Median:  {statistics.median(response_times):.3f}s")

        if len(response_times) > 1:
            print(f"   Std Dev: {statistics.stdev(response_times):.3f}s")

        # Performance thresholds
        print(f"\n🎯 Performance Assessment:")
        p50 = statistics.median(response_times)
        p95 = sorted(response_times)[int(len(response_times) * 0.95)] if len(response_times) > 1 else response_times[0]

        print(f"   P50: {p50:.3f}s {'✅' if p50 < 1.0 else '⚠️' if p50 < 2.0 else '❌'}")
        print(f"   P95: {p95:.3f}s {'✅' if p95 < 2.0 else '⚠️' if p95 < 5.0 else '❌'}")

        if p50 < 1.0:
            print(f"\n✅ PASS: Median response time under 1 second - excellent performance!")
        elif p50 < 2.0:
            print(f"\n⚠️  WARNING: Median response time {p50:.2f}s - consider adding caching")
        else:
            print(f"\n❌ FAIL: Median response time {p50:.2f}s - caching highly recommended")

        if len(failed) > len(results) * 0.1:
            print(f"\n❌ FAIL: >10% failure rate - server may be overloaded")
    else:
        print("\n❌ All requests failed!")
        for r in failed[:10]:
            print(f"   - {r['error']}")


def main():
    parser = argparse.ArgumentParser(description='Load test error clustering endpoint')
    parser.add_argument('--url', default='http://localhost:8000', help='Base URL of API server')
    parser.add_argument('--release', default='7.0.0.0', help='Release name')
    parser.add_argument('--module', default='business_policy', help='Module name')
    parser.add_argument('--job-id', default='1', help='Job ID')
    parser.add_argument('--concurrent', type=int, default=10, help='Concurrent requests per iteration')
    parser.add_argument('--iterations', type=int, default=3, help='Number of iterations')

    args = parser.parse_args()

    endpoint = f"/api/v1/jobs/{args.release}/{args.module}/{args.job_id}/failures/clustered"

    results = asyncio.run(run_concurrent_requests(
        base_url=args.url,
        endpoint=endpoint,
        concurrent=args.concurrent,
        iterations=args.iterations
    ))

    analyze_results(results)


if __name__ == '__main__':
    main()
