import { useState, useEffect } from 'react';

export function useLiveClock() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(new Date());
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return {
    time,
    timeString: time.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    dateString: time.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
  };
}
