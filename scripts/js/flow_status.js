page => page.evaluate(async () => {
  const videos = [...document.querySelectorAll('video')];
  // Flow renders <video> tiles lazily: the element has a src but readyState 0
  // and duration 0 until it is loaded. Force metadata to load so a finished
  // clip is detected as ready instead of polling forever on duration 0.
  await Promise.all(videos.map((v) => new Promise((res) => {
    if (v.readyState >= 1 && v.duration > 0) return res();
    try { v.muted = true; v.preload = 'metadata'; v.load(); } catch (e) {}
    if (v.readyState >= 1) return res();
    const t = setTimeout(res, 2500);
    v.addEventListener('loadedmetadata', () => { clearTimeout(t); res(); }, { once: true });
  })));
  const videoData = videos.map((video, index) => ({
    index,
    src: video.currentSrc || video.src || '',
    w: video.videoWidth || 0,
    h: video.videoHeight || 0,
    dur: Number.isFinite(video.duration) ? video.duration : 0,
  }));
  const readyVideos = videoData.filter(video => video.src && video.dur > 0);
  const selected = readyVideos[readyVideos.length - 1] || videoData[videoData.length - 1] || {};
  const text = document.body ? document.body.innerText : '';
  const busy = [...document.querySelectorAll('[aria-busy="true"], [data-loading="true"]')].length > 0;
  const generatingText = /Generating|Cancel|Stop|생성 중|취소|중지/i.test(text);
  return JSON.stringify({
    generating: busy || generatingText,
    videos: videos.length,
    src: selected.src || '',
    video_srcs: readyVideos.map(video => video.src),
    w: selected.w || 0,
    h: selected.h || 0,
    dur: selected.dur || 0,
    url: location.href,
  });
})
