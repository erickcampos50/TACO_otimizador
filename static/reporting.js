(function initReportingTools() {
  const REPORT_CONFIG = {
    markdown: {
      buttonId: 'exportReportMarkdownBtn',
      endpoint: '/api/reports/markdown',
      idleLabel: 'Relatório em Markdown',
      busyLabel: 'Gerando Markdown...',
      fallbackName: 'relatorio_cardapio_detalhado.md',
    },
    pdf: {
      buttonId: 'exportReportPdfBtn',
      endpoint: '/api/reports/pdf',
      idleLabel: 'Relatório em PDF',
      busyLabel: 'Gerando PDF...',
      fallbackName: 'relatorio_cardapio_detalhado.pdf',
    },
  };

  function appApi() {
    return window.tacoOptimizerApp || {};
  }

  function parseFilename(disposition, fallback) {
    if (!disposition) return fallback;
    const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
    return match ? match[1] : fallback;
  }

  function setReportButtonsEnabled(enabled) {
    Object.values(REPORT_CONFIG).forEach(({ buttonId }) => {
      const button = document.getElementById(buttonId);
      if (button) button.disabled = !enabled;
    });
  }

  async function downloadDetailedReport(format) {
    const config = REPORT_CONFIG[format];
    const button = document.getElementById(config.buttonId);
    const result = appApi().getResult?.();
    if (!result) {
      appApi().setMessage?.(appApi().getErrorBox?.(), ['Calcule o cardápio antes de gerar o relatório detalhado.']);
      return;
    }

    button.disabled = true;
    button.textContent = config.busyLabel;
    appApi().setMessage?.(appApi().getErrorBox?.(), [], true);

    try {
      const response = await fetch(config.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result }),
      });

      if (!response.ok) {
        let errors = [`Não foi possível gerar o relatório em ${format.toUpperCase()}.`];
        if (response.status === 404) {
          errors = [
            `Não foi possível gerar o relatório em ${format.toUpperCase()}.`,
            'O servidor que está rodando parece desatualizado e ainda não conhece essa rota de relatório.',
            'Reinicie a aplicação em http://127.0.0.1:5589 para carregar a versão mais recente do backend.',
          ];
        }
        try {
          const data = await response.json();
          errors = response.status === 404 ? errors : (data.detail?.errors || errors);
        } catch (err) {
          // Keep the fallback message when the response is not JSON.
        }
        appApi().setMessage?.(appApi().getErrorBox?.(), errors);
        return;
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = parseFilename(response.headers.get('Content-Disposition'), config.fallbackName);
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      appApi().setMessage?.(appApi().getErrorBox?.(), [String(err)]);
    } finally {
      button.disabled = false;
      button.textContent = config.idleLabel;
    }
  }

  function bindReportButtons() {
    Object.keys(REPORT_CONFIG).forEach((format) => {
      const config = REPORT_CONFIG[format];
      const button = document.getElementById(config.buttonId);
      if (!button || button.dataset.bound === 'true') return;
      button.dataset.bound = 'true';
      button.addEventListener('click', () => downloadDetailedReport(format));
    });
  }

  window.tacoReporting = {
    bindReportButtons,
    downloadDetailedReport,
    setReportButtonsEnabled,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindReportButtons);
  } else {
    bindReportButtons();
  }
})();
