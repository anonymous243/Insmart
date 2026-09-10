import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';

import { AdminLayout } from './components/AdminLayout';
import { Overview } from './pages/Overview';
import { CodeMaster } from './pages/CodeMaster';
import { Transactions } from './pages/Transactions';
import { FWABenchmark } from './pages/FWABenchmark';
import { Adjudication } from './pages/Adjudication';
import { AuditLogs } from './pages/AuditLogs';

import { FacilityLayout } from './components/FacilityLayout';
import { Login } from './pages/facility/Login';
import { Signup } from './pages/facility/Signup';
import { Dashboard } from './pages/facility/Dashboard';
import { NewSubmission } from './pages/facility/NewSubmission';
import { History } from './pages/facility/History';
import { Account } from './pages/facility/Account';

const ProtectedFacilityRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      
      {/* Auth */}
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />

      {/* Facility Application */}
      <Route path="/facility" element={
        <ProtectedFacilityRoute>
          <FacilityLayout />
        </ProtectedFacilityRoute>
      }>
        <Route index element={<Dashboard />} />
        <Route path="new" element={<NewSubmission />} />
        <Route path="history" element={<History />} />
        <Route path="account" element={<Account />} />
      </Route>

      {/* Central Admin Application */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<Overview />} />
        <Route path="codes" element={<CodeMaster />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="fwa" element={<FWABenchmark />} />
        <Route path="adjudication" element={<Adjudication />} />
        <Route path="audit" element={<AuditLogs />} />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
