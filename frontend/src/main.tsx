import React from 'react';
import ReactDOM from 'react-dom/client';
import { Providers } from './components/Providers';
import App from './App';
import './styles/base.css';
import './styles/workspace.css';

if (!location.pathname.endsWith('/')) {
  location.replace(location.pathname + '/' + location.search + location.hash);
} else {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode><Providers><App /></Providers></React.StrictMode>,
  );
}
