function initAutoRefresh() {
  const streamUrl = document.body.dataset.streamUrl;
  if (!streamUrl) {
    return;
  }

  const source = new EventSource(streamUrl);
  source.onmessage = () => {
    window.location.reload();
  };
  source.addEventListener("run_update", () => {
    window.location.reload();
  });
  source.addEventListener("run_event", () => {
    window.location.reload();
  });
  source.onerror = () => {
    source.close();
    window.setTimeout(initAutoRefresh, 1500);
  };
}

window.addEventListener("DOMContentLoaded", initAutoRefresh);
