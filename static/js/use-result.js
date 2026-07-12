(function () {
  const statusBadge = document.getElementById('statusBadge');
  const statusText = document.getElementById('statusText');
  const resultBox = document.getElementById('resultBox');
  const resultPlatform = document.getElementById('resultPlatform');
  const resultPath = document.getElementById('resultPath');
  const resultError = document.getElementById('resultError');
  const resultErrorRow = document.getElementById('resultErrorRow');
  const resultQuality = document.getElementById('resultQuality');
  const resultQualityRow = document.getElementById('resultQualityRow');
  const resultWarning = document.getElementById('resultWarning');
  const resultWarningRow = document.getElementById('resultWarningRow');
  const recentCard = document.getElementById('recentCard');
  const recentTitle = document.getElementById('recentTitle');

  function setStatus(kind, text) {
    if (statusBadge) {
      statusBadge.textContent = kind === 'running'
        ? '⌛ 处理中'
        : kind === 'success'
          ? '✓ 完成'
          : kind === 'error'
            ? '⚠ 失败'
            : '• 待执行';
      statusBadge.style.color = kind === 'running'
        ? '#9a6b28'
        : kind === 'success'
          ? '#4b9c5e'
          : kind === 'error'
            ? '#c45858'
            : '';
    }

    if (statusText) {
      statusText.textContent = text;
    }

    if (!recentTitle) {
      return;
    }

    if (kind === 'running') {
      recentTitle.textContent = '正在解析链接';
      recentCard?.classList.add('processing');
    } else if (kind === 'success') {
      recentTitle.textContent = '解析完成的视频';
      recentCard?.classList.remove('processing');
    } else if (kind === 'error') {
      recentTitle.textContent = '解析失败';
      recentCard?.classList.remove('processing');
    } else {
      recentTitle.textContent = '等待新的解析任务';
      recentCard?.classList.remove('processing');
    }
  }

  function showResult({ path = '', platform = '', error = '', validation = null } = {}) {
    if (!resultBox || !resultPath || !resultPlatform || !resultError || !resultErrorRow) {
      return;
    }

    resultPlatform.textContent = platform || '-';
    resultPath.textContent = path || '-';

    const qualityParts = [];
    if (validation) {
      if (validation.width && validation.height) qualityParts.push(`${validation.width}×${validation.height}`);
      if (validation.videoCodec) qualityParts.push(String(validation.videoCodec).toUpperCase());
      if (validation.audioCodec) qualityParts.push(String(validation.audioCodec).toUpperCase());
      if (validation.bitrate) qualityParts.push(`${Math.round(Number(validation.bitrate) / 1000)} kbps`);
      if (validation.qualityScore !== undefined) qualityParts.push(`评分 ${validation.qualityScore}`);
    }
    if (resultQuality && resultQualityRow) {
      resultQuality.textContent = qualityParts.join(' · ') || '-';
      resultQualityRow.hidden = qualityParts.length === 0;
    }
    const warnings = Array.isArray(validation?.warnings) ? validation.warnings : [];
    if (resultWarning && resultWarningRow) {
      resultWarning.textContent = warnings.join('；') || '-';
      resultWarningRow.hidden = warnings.length === 0;
    }

    if (error) {
      resultError.textContent = error;
      resultErrorRow.hidden = false;
    } else {
      resultError.textContent = '-';
      resultErrorRow.hidden = true;
    }

    resultBox.hidden = !(path || platform || error);
  }

  window.StreamDockResult = {
    setStatus,
    showResult,
  };
})();
