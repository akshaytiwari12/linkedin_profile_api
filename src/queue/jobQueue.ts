// In-memory FIFO of job ids waiting to be processed. Deliberately dumb — all the interesting
// behavior (pacing, retries, circuit breaking) lives in sessionManager/worker, not here. Swap
// this for a real broker (SQS/Redis streams/etc.) if this ever needs to run across processes.
const queue: string[] = [];

export function enqueue(jobId: string): void {
  queue.push(jobId);
}

export function dequeue(): string | undefined {
  return queue.shift();
}

export function queueLength(): number {
  return queue.length;
}
