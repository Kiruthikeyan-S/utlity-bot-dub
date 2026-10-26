import React, { useState, useEffect, useRef } from 'react';
import { 
  X, 
  Trash2, 
  FileText, 
  Search, 
  RefreshCw, 
  ChevronRight, 
  Clock, 
  HardDrive, 
  AlertCircle, 
  Image as ImageIcon,
  Package,
  QrCode,
  Scan,
  Copy,
  Check
} from 'lucide-react';
import { 
  getHistoryApi, 
  deleteHistoryApi, 
  getStorageStatsApi, 
  cleanStorageApi, 
  getDeviceId,
  getShippingHistoryApi,
  deleteShippingByIdApi,
  getQrHistoryApi,
  deleteQrByIdApi
} from '../services/api';
import { getLocalRecords, saveLocalRecord, deleteLocalRecord, cleanExpiredLocalRecords } from '../services/localStore';

export default function HistoryDrawer({ 
  isOpen, 
  onClose, 
  onSelectDocument, 
  onSelectShipping,
  onSelectQr,
  currentUser 
}) {
  // 4 Category Tabs: 'id' | 'shipping' | 'qr_gen' | 'qr_scan'
  const [activeCategory, setActiveCategory] = useState('id');

  const [idHistory, setIdHistory] = useState([]);
  const [shippingHistory, setShippingHistory] = useState([]);
  const [qrGenHistory, setQrGenHistory] = useState([]);
  const [qrScanHistory, setQrScanHistory] = useState([]);

  const [stats, setStats] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [isCleaning, setIsCleaning] = useState(false);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  const activeRequestUidRef = useRef(null);

  // Clear displayed history immediately when account switches
  useEffect(() => {
    activeRequestUidRef.current = currentUser?.uid || null;
    setIdHistory([]);
    setShippingHistory([]);
    setQrGenHistory([]);
    setQrScanHistory([]);
    setStats(null);
    setLoadError(null);
  }, [currentUser?.uid]);

  const fetchCategoryHistory = async () => {
    const ownerUid = currentUser?.uid;
    if (!ownerUid) {
      setIdHistory([]);
      setShippingHistory([]);
      setQrGenHistory([]);
      setQrScanHistory([]);
      setStats(null);
      setIsLoading(false);
      return;
    }

    activeRequestUidRef.current = ownerUid;
    setIsLoading(true);
    setLoadError(null);
    const deviceId = getDeviceId();

    try {
      getStorageStatsApi()
        .then(res => {
          if (activeRequestUidRef.current === ownerUid) setStats(res);
        })
        .catch(() => {});

      if (activeCategory === 'id') {
        const [historyData, localRecords] = await Promise.all([
          getHistoryApi({ limit: 50, doc_type: typeFilter || undefined }),
          getLocalRecords(ownerUid).catch(() => []),
        ]);

        if (activeRequestUidRef.current !== ownerUid) return;

        const remoteDocs = historyData?.documents || [];
        for (const doc of remoteDocs) {
          saveLocalRecord(doc, ownerUid, deviceId).catch(() => {});
        }

        const map = new Map();
        for (const doc of localRecords) {
          if (doc._id) map.set(doc._id, doc);
        }
        for (const doc of remoteDocs) {
          if (doc._id) map.set(doc._id, doc);
        }

        let combined = Array.from(map.values());
        if (typeFilter) {
          combined = combined.filter((d) => (d.documentType || d.document_type) === typeFilter);
        }
        combined.sort((a, b) => new Date(b.createdAt || 0) - new Date(a.createdAt || 0));
        setIdHistory(combined);

      } else if (activeCategory === 'shipping') {
        const data = await getShippingHistoryApi({ limit: 50 });
        if (activeRequestUidRef.current !== ownerUid) return;
        setShippingHistory(data?.documents || []);

      } else if (activeCategory === 'qr_gen') {
        const data = await getQrHistoryApi({ limit: 50, action_type: 'generate' });
        if (activeRequestUidRef.current !== ownerUid) return;
        setQrGenHistory(data?.documents || []);

      } else if (activeCategory === 'qr_scan') {
        const data = await getQrHistoryApi({ limit: 50, action_type: 'scan' });
        if (activeRequestUidRef.current !== ownerUid) return;
        setQrScanHistory(data?.documents || []);
      }

    } catch (e) {
      console.error('Failed to fetch history:', e);
      if (activeRequestUidRef.current === ownerUid) {
        setLoadError(e.response?.data?.detail || e.message || 'Failed to load history records.');
      }
    } finally {
      if (activeRequestUidRef.current === ownerUid) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    if (isOpen && currentUser?.uid) {
      fetchCategoryHistory();
    }
  }, [isOpen, activeCategory, typeFilter, currentUser?.uid]);

  const handleDeleteItem = async (e, id, category) => {
    e.stopPropagation();
    if (!window.confirm('Delete this history record?')) return;
    try {
      if (category === 'id') {
        await deleteHistoryApi(id);
        if (currentUser?.uid) {
          await deleteLocalRecord(id, currentUser.uid);
        }
        setIdHistory((prev) => prev.filter((d) => d._id !== id));
      } else if (category === 'shipping') {
        await deleteShippingByIdApi(id);
        setShippingHistory((prev) => prev.filter((d) => d._id !== id));
      } else {
        await deleteQrByIdApi(id);
        if (category === 'qr_gen') {
          setQrGenHistory((prev) => prev.filter((d) => d._id !== id));
        } else {
          setQrScanHistory((prev) => prev.filter((d) => d._id !== id));
        }
      }
      getStorageStatsApi().then(setStats).catch(() => {});
    } catch (e) {
      alert('Failed to delete record: ' + (e.response?.data?.detail || e.message));
    }
  };

  const handleCleanStorage = async () => {
    if (!window.confirm('Purge expired records (>30 days) from storage across all tools? Fresh records will be preserved.')) return;
    setIsCleaning(true);
    try {
      const res = await cleanStorageApi(false);
      if (currentUser?.uid) {
        await cleanExpiredLocalRecords(currentUser.uid, 30);
      }
      await fetchCategoryHistory();
      if (res?.message) {
        alert(res.message);
      }
    } catch (e) {
      alert('Failed to clean storage.');
    } finally {
      setIsCleaning(false);
    }
  };

  const handleCopyText = (e, text, id) => {
    e.stopPropagation();
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  const getDaysRemaining = (createdAtStr) => {
    if (!createdAtStr) return '30d';
    try {
      const created = new Date(createdAtStr);
      const now = new Date();
      const diffDays = Math.max(0, 30 - Math.floor((now - created) / (1000 * 60 * 60 * 24)));
      return `${diffDays} days left`;
    } catch {
      return '30d';
    }
  };

  if (!isOpen) return null;

  // Filter current active list
  const currentList = 
    activeCategory === 'id' ? idHistory :
    activeCategory === 'shipping' ? shippingHistory :
    activeCategory === 'qr_gen' ? qrGenHistory : qrScanHistory;

  const filteredItems = currentList.filter((item) => {
    if (!search.trim()) return true;
    const term = search.toLowerCase();
    const str = JSON.stringify(item).toLowerCase();
    return str.includes(term);
  });

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div 
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm transition-opacity"
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-6 sm:pl-10">
        <div className="w-screen max-w-lg bg-white border-l border-slate-200 shadow-2xl flex flex-col">
          
          {/* Header */}
          <div className="p-4 sm:p-5 border-b border-slate-200 flex items-center justify-between bg-slate-50">
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold text-slate-900">Unified History</h2>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
                  30-Day Auto Retention
                </span>
              </div>
              <div className="flex items-center space-x-1.5 text-xs text-slate-500 mt-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block"></span>
                <span>User: {currentUser?.email || currentUser?.uid}</span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-white hover:bg-slate-100 text-slate-500 hover:text-slate-700 border border-slate-200 transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Storage Meter Bar */}
          {stats && (
            <div className="px-5 py-2.5 bg-slate-50/80 border-b border-slate-200 text-xs">
              <div className="flex items-center justify-between text-slate-600 mb-1 font-medium">
                <div className="flex items-center space-x-1.5">
                  <HardDrive className="w-3.5 h-3.5 text-sky-600" />
                  <span>Cloud Usage:</span>
                  <strong className="text-slate-800">{stats.storageSizeKB} KB ({stats.totalRecords}/{stats.maxRecords} records)</strong>
                </div>
                <button
                  onClick={handleCleanStorage}
                  disabled={isCleaning}
                  className="text-[11px] font-semibold text-rose-600 hover:text-rose-700 underline"
                >
                  {isCleaning ? 'Cleaning...' : 'Clean Storage'}
                </button>
              </div>
              <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div 
                  className={`h-full transition-all duration-300 ${
                    stats.percentUsed > 80 ? 'bg-rose-500' : stats.percentUsed > 50 ? 'bg-amber-500' : 'bg-sky-600'
                  }`}
                  style={{ width: `${Math.max(4, stats.percentUsed)}%` }}
                />
              </div>
            </div>
          )}

          {/* 4 Category Tabs */}
          <div className="grid grid-cols-4 p-2 bg-slate-100/80 border-b border-slate-200 gap-1 text-[11px] font-bold">
            <button
              onClick={() => { setActiveCategory('id'); setSearch(''); }}
              className={`py-2 px-1 rounded-xl flex flex-col sm:flex-row items-center justify-center space-x-1 transition ${
                activeCategory === 'id' 
                  ? 'bg-white text-sky-700 shadow-sm border border-slate-200' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>ID Cards</span>
            </button>

            <button
              onClick={() => { setActiveCategory('shipping'); setSearch(''); }}
              className={`py-2 px-1 rounded-xl flex flex-col sm:flex-row items-center justify-center space-x-1 transition ${
                activeCategory === 'shipping' 
                  ? 'bg-white text-indigo-700 shadow-sm border border-slate-200' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <Package className="w-3.5 h-3.5" />
              <span>Shipping</span>
            </button>

            <button
              onClick={() => { setActiveCategory('qr_gen'); setSearch(''); }}
              className={`py-2 px-1 rounded-xl flex flex-col sm:flex-row items-center justify-center space-x-1 transition ${
                activeCategory === 'qr_gen' 
                  ? 'bg-white text-teal-700 shadow-sm border border-slate-200' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <QrCode className="w-3.5 h-3.5" />
              <span>QR Gen</span>
            </button>

            <button
              onClick={() => { setActiveCategory('qr_scan'); setSearch(''); }}
              className={`py-2 px-1 rounded-xl flex flex-col sm:flex-row items-center justify-center space-x-1 transition ${
                activeCategory === 'qr_scan' 
                  ? 'bg-white text-purple-700 shadow-sm border border-slate-200' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <Scan className="w-3.5 h-3.5" />
              <span>Scans</span>
            </button>
          </div>

          {/* Search Bar & ID Sub-filters */}
          <div className="p-3 border-b border-slate-100 bg-white space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder={
                  activeCategory === 'id' ? 'Search by name, ID number, filename...' :
                  activeCategory === 'shipping' ? 'Search tracking number, carrier, sender, receiver...' :
                  activeCategory === 'qr_gen' ? 'Search QR payload, Wi-Fi SSID, URL...' :
                  'Search decoded barcodes, QR text, OCR lines...'
                }
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-800 focus:outline-none focus:border-sky-500"
              />
            </div>

            {activeCategory === 'id' && (
              <div className="flex gap-1.5 overflow-x-auto pb-0.5">
                {['', 'aadhaar', 'pan', 'driving_licence'].map((t) => (
                  <button
                    key={t}
                    onClick={() => setTypeFilter(t)}
                    className={`text-[10px] px-2.5 py-1 rounded-lg font-bold capitalize transition ${
                      typeFilter === t
                        ? 'bg-sky-600 text-white shadow-sm'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {t === '' ? 'All Types' : t.replace('_', ' ')}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* List Area with Honest Loading, Error, and Empty States */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/50">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400">
                <RefreshCw className="w-7 h-7 animate-spin text-sky-600 mb-2" />
                <p className="text-xs font-semibold text-slate-600">Loading {activeCategory.replace('_', ' ')} history...</p>
                <p className="text-[11px] text-slate-400 mt-0.5">Querying verified cloud & local records</p>
              </div>
            ) : loadError ? (
              <div className="p-5 bg-rose-50 border border-rose-200 rounded-2xl text-center space-y-2">
                <AlertCircle className="w-7 h-7 text-rose-600 mx-auto" />
                <h4 className="text-xs font-bold text-rose-900">Failed to load history</h4>
                <p className="text-[11px] text-rose-700">{loadError}</p>
                <button
                  onClick={fetchCategoryHistory}
                  className="px-4 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-xl transition shadow-sm"
                >
                  Retry Request
                </button>
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                {activeCategory === 'id' && <FileText className="w-10 h-10 mx-auto mb-2 text-slate-300" />}
                {activeCategory === 'shipping' && <Package className="w-10 h-10 mx-auto mb-2 text-slate-300" />}
                {activeCategory === 'qr_gen' && <QrCode className="w-10 h-10 mx-auto mb-2 text-slate-300" />}
                {activeCategory === 'qr_scan' && <Scan className="w-10 h-10 mx-auto mb-2 text-slate-300" />}
                <p className="text-xs font-bold text-slate-700">No records found</p>
                <p className="text-[11px] text-slate-500 mt-1 max-w-xs mx-auto">
                  {activeCategory === 'id' && 'Confirmed ID document records will be stored here for 30 days.'}
                  {activeCategory === 'shipping' && 'Scanned shipping label extractions will appear here.'}
                  {activeCategory === 'qr_gen' && 'Generated verified QR codes will be saved here.'}
                  {activeCategory === 'qr_scan' && 'Decoded barcode and QR scan results will be saved here.'}
                </p>
              </div>
            ) : (
              /* ================= RENDERING ITEMS BY CATEGORY ================= */
              filteredItems.map((doc) => {
                if (activeCategory === 'id') {
                  return (
                    <div
                      key={doc._id}
                      onClick={() => {
                        if (onSelectDocument) {
                          onSelectDocument(doc);
                        }
                        onClose();
                      }}
                      className="bg-white border border-slate-200 rounded-xl p-3 hover:border-sky-400 hover:shadow-sm cursor-pointer transition flex items-center justify-between group gap-3"
                    >
                      <div className="w-12 h-12 rounded-lg bg-slate-100 border border-slate-200 overflow-hidden flex-shrink-0 flex items-center justify-center">
                        {doc.thumbnail ? (
                          <img src={doc.thumbnail} alt="Doc thumbnail" className="w-full h-full object-cover" />
                        ) : (
                          <ImageIcon className="w-5 h-5 text-slate-400" />
                        )}
                      </div>

                      <div className="overflow-hidden flex-1">
                        <div className="flex items-center space-x-2 mb-0.5">
                          <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200">
                            {doc.documentType || 'document'}
                          </span>
                          <span className="text-[10px] font-medium text-amber-700 flex items-center space-x-0.5">
                            <Clock className="w-2.5 h-2.5" />
                            <span>{getDaysRemaining(doc.createdAt)}</span>
                          </span>
                        </div>
                        <h4 className="text-xs font-bold text-slate-800 truncate">
                          {doc.data?.name || doc.originalFileName || 'Unnamed Applicant'}
                        </h4>
                        <p className="text-[11px] font-mono text-slate-500 truncate">
                          {doc.data?.aadhaar_number || doc.data?.pan_number || doc.data?.dl_number || doc._id}
                        </p>
                      </div>

                      <div className="flex items-center space-x-1 flex-shrink-0">
                        <button
                          onClick={(e) => handleDeleteItem(e, doc._id, 'id')}
                          className="p-1.5 text-slate-400 hover:text-rose-600 rounded-md hover:bg-rose-50 transition"
                          title="Delete record"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-sky-600 transition" />
                      </div>
                    </div>
                  );
                }

                if (activeCategory === 'shipping') {
                  const tracking = doc.tracking_number || doc.extracted_data?.tracking_number || 'No Tracking';
                  const carrier = doc.carrier || doc.extracted_data?.carrier || 'Shipping Label';
                  const toName = doc.receiver?.name || doc.extracted_data?.receiver?.name || 'Receiver';

                  return (
                    <div
                      key={doc._id}
                      onClick={() => {
                        if (onSelectShipping) {
                          onSelectShipping(doc);
                        }
                        onClose();
                      }}
                      className="bg-white border border-slate-200 rounded-xl p-3 hover:border-indigo-400 hover:shadow-sm cursor-pointer transition flex items-center justify-between group gap-3"
                    >
                      <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 flex-shrink-0">
                        <Package className="w-5 h-5" />
                      </div>

                      <div className="overflow-hidden flex-1">
                        <div className="flex items-center space-x-2 mb-0.5">
                          <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
                            {carrier}
                          </span>
                          <span className="text-[10px] font-medium text-amber-700 flex items-center space-x-0.5">
                            <Clock className="w-2.5 h-2.5" />
                            <span>{getDaysRemaining(doc.createdAt)}</span>
                          </span>
                        </div>
                        <h4 className="text-xs font-bold text-slate-800 truncate">
                          Tracking: {tracking}
                        </h4>
                        <p className="text-[11px] text-slate-500 truncate">
                          To: {toName} {doc.receiver?.city ? `(${doc.receiver.city})` : ''}
                        </p>
                      </div>

                      <div className="flex items-center space-x-1 flex-shrink-0">
                        <button
                          onClick={(e) => handleDeleteItem(e, doc._id, 'shipping')}
                          className="p-1.5 text-slate-400 hover:text-rose-600 rounded-md hover:bg-rose-50 transition"
                          title="Delete shipping record"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-indigo-600 transition" />
                      </div>
                    </div>
                  );
                }

                if (activeCategory === 'qr_gen') {
                  const content = doc.content || '';
                  const qrType = doc.qr_type || 'text';

                  return (
                    <div
                      key={doc._id}
                      onClick={() => {
                        if (onSelectQr) {
                          onSelectQr(doc);
                        }
                        onClose();
                      }}
                      className="bg-white border border-slate-200 rounded-xl p-3 hover:border-teal-400 hover:shadow-sm cursor-pointer transition flex items-center justify-between group gap-3"
                    >
                      <div className="w-10 h-10 rounded-xl bg-teal-50 border border-teal-100 flex items-center justify-center text-teal-600 flex-shrink-0">
                        <QrCode className="w-5 h-5" />
                      </div>

                      <div className="overflow-hidden flex-1">
                        <div className="flex items-center space-x-2 mb-0.5">
                          <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-teal-50 text-teal-800 border border-teal-200">
                            {qrType}
                          </span>
                          <span className="text-[10px] font-medium text-amber-700 flex items-center space-x-0.5">
                            <Clock className="w-2.5 h-2.5" />
                            <span>{getDaysRemaining(doc.createdAt)}</span>
                          </span>
                        </div>
                        <h4 className="text-xs font-bold text-slate-800 truncate font-mono">
                          {content.length > 50 ? content.slice(0, 50) + '...' : content || 'Empty QR'}
                        </h4>
                        <p className="text-[10px] text-slate-400">
                          {doc.metadata?.format?.toUpperCase() || 'PNG'} • {doc.metadata?.size || 400}px • Error Lvl: {doc.metadata?.error_correction || 'M'}
                        </p>
                      </div>

                      <div className="flex items-center space-x-1 flex-shrink-0">
                        <button
                          onClick={(e) => handleCopyText(e, content, doc._id)}
                          className="p-1.5 text-slate-400 hover:text-teal-600 rounded-md hover:bg-teal-50 transition"
                          title="Copy payload"
                        >
                          {copiedId === doc._id ? <Check className="w-3.5 h-3.5 text-teal-600" /> : <Copy className="w-3.5 h-3.5" />}
                        </button>
                        <button
                          onClick={(e) => handleDeleteItem(e, doc._id, 'qr_gen')}
                          className="p-1.5 text-slate-400 hover:text-rose-600 rounded-md hover:bg-rose-50 transition"
                          title="Delete QR record"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-teal-600 transition" />
                      </div>
                    </div>
                  );
                }

                // activeCategory === 'qr_scan'
                const barcodeCount = doc.barcodes?.length || 0;
                const qrCount = doc.qr_codes?.length || 0;
                const content = doc.content || (doc.barcodes?.[0]?.data || doc.qr_codes?.[0]?.data || 'Optical Code');

                return (
                  <div
                    key={doc._id}
                    onClick={() => {
                      if (onSelectQr) {
                        onSelectQr(doc);
                      }
                      onClose();
                    }}
                    className="bg-white border border-slate-200 rounded-xl p-3 hover:border-purple-400 hover:shadow-sm cursor-pointer transition flex items-center justify-between group gap-3"
                  >
                    <div className="w-10 h-10 rounded-xl bg-purple-50 border border-purple-100 flex items-center justify-center text-purple-600 flex-shrink-0">
                      <Scan className="w-5 h-5" />
                    </div>

                    <div className="overflow-hidden flex-1">
                      <div className="flex items-center space-x-2 mb-0.5">
                        <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-purple-50 text-purple-800 border border-purple-200">
                          {barcodeCount > 0 ? `${barcodeCount} Barcode${barcodeCount > 1 ? 's' : ''}` : ''}
                          {barcodeCount > 0 && qrCount > 0 ? ' + ' : ''}
                          {qrCount > 0 ? `${qrCount} QR` : ''}
                          {barcodeCount === 0 && qrCount === 0 ? 'Code Scan' : ''}
                        </span>
                        <span className="text-[10px] font-medium text-amber-700 flex items-center space-x-0.5">
                          <Clock className="w-2.5 h-2.5" />
                          <span>{getDaysRemaining(doc.createdAt)}</span>
                        </span>
                      </div>
                      <h4 className="text-xs font-bold text-slate-800 truncate font-mono">
                        {content}
                      </h4>
                      {doc.metadata?.filename && (
                        <p className="text-[10px] text-slate-400 truncate">
                          File: {doc.metadata.filename}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center space-x-1 flex-shrink-0">
                      <button
                        onClick={(e) => handleCopyText(e, content, doc._id)}
                        className="p-1.5 text-slate-400 hover:text-purple-600 rounded-md hover:bg-purple-50 transition"
                        title="Copy text"
                      >
                        {copiedId === doc._id ? <Check className="w-3.5 h-3.5 text-purple-600" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                      <button
                        onClick={(e) => handleDeleteItem(e, doc._id, 'qr_scan')}
                        className="p-1.5 text-slate-400 hover:text-rose-600 rounded-md hover:bg-rose-50 transition"
                        title="Delete scan record"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-purple-600 transition" />
                    </div>
                  </div>
                );
              })
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
