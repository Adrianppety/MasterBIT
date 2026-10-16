import React, { useCallback, useEffect } from 'react';
import './PackAlertPopup.css';

const PackAlertPopup = ({ isVisible, onClose }) => {
  const closePopup = useCallback(() => {
    if (typeof onClose === 'function') {
      onClose();
    }
  }, [onClose]);

  useEffect(() => {
    if (!isVisible) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      closePopup();
    }, 8000);

    return () => window.clearTimeout(timer);
  }, [closePopup, isVisible]);

  useEffect(() => {
    if (!isVisible) {
      return undefined;
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        closePopup();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [closePopup, isVisible]);

  if (!isVisible) {
    return null;
  }

  return (
    <div className="popup-overlay" role="presentation">
      <div className="popup-alert" role="alertdialog" aria-modal="true" aria-labelledby="pack-alert-title">
        <div className="card-icon">
          <img src="/imagem/Gemini_Generated_Image_1palfx1palfx1pal-Photoroom.png" alt="" aria-hidden="true" />
        </div>
        <h2 id="pack-alert-title" className="popup-title">ATENÇÃO: PACOTES COM DADOS INCOMPLETOS</h2>
        <p className="popup-message">
          Alguns pacotes não tiveram valores possíveis<br />
          <span className="highlight">de serem colocados</span>, mas as cartas <span className="highlight">estão lá!</span>
        </p>
        <button type="button" className="popup-button" onClick={closePopup} tabIndex={0}>
          ENTENDIDO
        </button>
      </div>
    </div>
  );
};

export default PackAlertPopup;