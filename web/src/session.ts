// These are browser recovery pointers; the underlying records remain on the server.
export function clearAccountSessionCache(userId:string):void {
  try {
    const keys=Object.keys(sessionStorage);
    for(const key of keys) {
      if(key===`campus-guide-conversation:${userId}`||key===`campus-guide-run:${userId}`||key.startsWith(`campus-stage-run:${userId}:`)) {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Storage can be disabled; the server session is still revoked on logout.
  }
}
