import React, { useState, useEffect } from 'react';
import { QrCode, Scan, Layers } from 'lucide-react';
import QRGenerator from './QRGenerator';
import QRScanner from './QRScanner';

export default function QRTools({ sessionState = null, onSessionStateChange = null }) {
  const [activeTab, setActiveTab] = useState(sessionState?.activeTab || 'generate'); // 'generate' | 'scan'

  useEffect(() => {
    if (sessionState?.activeTab && sessionState.activeTab !== activeTab) {
      setActiveTab(sessionState.activeTab);
    }
  }, [sessionState?.activeTab]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (onSessionStateChange) {
      onSessionStateChange(prev => ({ ...prev, activeTab: tab }));
    }
  };

  const handleGeneratorState = (genData) => {
    if (onSessionStateChange) {
      onSessionStateChange(prev => ({ ...prev, generatorData: genData }));
    }
  };

  const handleScannerState = (scanData) => {
    if (onSessionStateChange) {
      onSessionStateChange(prev => ({ ...prev, scannerData: scanData }));
    }
  };

  return (
    <div className="space-y-6">
      
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 flex items-center space-x-2">
            <span className="p-1.5 rounded-xl bg-sky-50 text-sky-600 border border-sky-100">
              <QrCode className="w-5 h-5" />
            </span>
            <span>QR &amp; Barcode Tools</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Generate verified standard QR codes &amp; scan all 1D/2D optical symbologies locally.
          </p>
        </div>

        {/* Top Tab Switcher */}
        <div className="bg-slate-100 p-1 rounded-2xl flex items-center space-x-1 self-start sm:self-auto border border-slate-200/80">
          <button
            onClick={() => handleTabChange('generate')}
            className={`flex items-center space-x-2 py-2 px-4 rounded-xl text-xs font-bold transition ${
              activeTab === 'generate'
                ? 'bg-white text-sky-700 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <QrCode className="w-4 h-4" />
            <span>Generate QR</span>
          </button>

          <button
            onClick={() => handleTabChange('scan')}
            className={`flex items-center space-x-2 py-2 px-4 rounded-xl text-xs font-bold transition ${
              activeTab === 'scan'
                ? 'bg-white text-indigo-700 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <Scan className="w-4 h-4" />
            <span>Scan QR / Barcode</span>
          </button>
        </div>
      </div>

      {/* Main Tab Content */}
      <div className="transition-all duration-200">
        {activeTab === 'generate' && (
          <QRGenerator 
            initialData={sessionState?.generatorData} 
            onStateChange={handleGeneratorState}
          />
        )}
        {activeTab === 'scan' && (
          <QRScanner 
            initialData={sessionState?.scannerData}
            onStateChange={handleScannerState}
          />
        )}
      </div>

    </div>
  );
}
