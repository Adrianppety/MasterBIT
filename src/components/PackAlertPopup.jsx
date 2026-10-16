import React, { useState, useEffect } from 'react';
import './PackAlertPopup.css';

const PackAlertPopup = ({ isVisible, onClose }) => {
  useEffect(() => {
    // Auto-close after 8 seconds
    if (isVisible) {
      const timer = setTimeout(() => {
        onClose();
      }, 8000);
      return () => clearTimeout(timer);
    }
  }, [isVisible, onClose]);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  useEffect(() => {
    if (isVisible) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isVisible]);

  if (!isVisible) return null;

  return (
    <div className="popup-alert" role="alert" aria-modal="true">
      <div className="card-icon" aria-hidden="true"></div>
      <h2 className="popup-title">ATENÇÃO: PACOTES COM DADOS INCOMPLETOS</h2>
      <p className="popup-message">
        Alguns pacotes não tiveram valores possíveis<br />
        <span className="highlight">de serem colocados</span>, mas as cartas <span className="highlight">estão lá!</span>
      </p>
      <button
        className="popup-button"
        onClick={onClose}
        onKeyDown={(e) => e.preventDefault()} // Prevent scrolling
        tabIndex={0}
      >
        ENTENDIDO
      </button>
    </div>
  );
};

export default PackAlertPopup;