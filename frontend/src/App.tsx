import { ErrorBoundary } from './components/ErrorBoundary';
import { GlassesHUD } from './components/GlassesHUD/GlassesHUD';
import { exemplarPatients } from './data/exemplarPatients';
import './App.css';

export default function App() {
  return (
    <ErrorBoundary>
      <GlassesHUD patient={exemplarPatients[2]} onClose={() => {}} />
    </ErrorBoundary>
  );
}
