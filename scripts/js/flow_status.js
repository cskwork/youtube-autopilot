page => page.evaluate(() => {
  const videos = [...document.querySelectorAll('video')];
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
