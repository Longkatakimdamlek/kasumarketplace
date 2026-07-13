/**
 * LiveCapture v2 — React + MediaPipe Face Landmarker
 * Drop into: vendors/static/vendors/js/live_capture.js
 * Requires React 18 UMD + MediaPipe Tasks Vision loaded before this file.
 */
(function () {
    const { useState, useEffect, useRef, useCallback } = React;

    const CDN_VISION_TASKS = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm';
    const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

    // ── Tunables ──────────────────────────────────────────────────────────
    const CENTER_TOLERANCE     = 0.12;
    const DISTANCE_MIN         = 0.28;
    const DISTANCE_MAX         = 0.55;
    const EYE_BLINK_MAX        = 0.4;
    // How many consecutive good frames before "Hold still" message shows
    const HOLD_FRAMES_REQUIRED = 20;   // ~0.67s at 30fps — was 8, now slower
    const COUNTDOWN_SECONDS    = 3;
    // During countdown: how many consecutive bad frames cancel it
    const CANCEL_FRAMES_REQUIRED = 4;

    // ── MediaPipe loader ─────────────────────────────────────────────────
    function useFaceLandmarker() {
      const [landmarker, setLandmarker] = useState(null);
      const [loadError,  setLoadError]  = useState(null);

      useEffect(() => {
        let cancelled = false;
        async function load() {
          if (!window.FaceLandmarksTasksVision) {
            await new Promise(res => window.addEventListener('mediapipe:ready', res, { once: true }));
          }
          try {
            const vision = await window.FaceLandmarksTasksVision.FilesetResolver.forVisionTasks(CDN_VISION_TASKS);
            const created = await window.FaceLandmarksTasksVision.FaceLandmarker.createFromOptions(vision, {
              baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
              outputFaceBlendshapes: true,
              runningMode: 'VIDEO',
              numFaces: 1,
            });
            if (!cancelled) setLandmarker(created);
          } catch (err) {
            console.error('FaceLandmarker load failed', err);
            if (!cancelled) setLoadError(err);
          }
        }
        load();
        return () => { cancelled = true; };
      }, []);

      return { landmarker, loadError };
    }

    // ── Helpers ───────────────────────────────────────────────────────────
    function getEyeOpenness(blendshapes) {
      if (!blendshapes?.length) return { open: false };
      const cats = blendshapes[0].categories || [];
      const l = cats.find(c => c.categoryName === 'eyeBlinkLeft')?.score  ?? 0;
      const r = cats.find(c => c.categoryName === 'eyeBlinkRight')?.score ?? 0;
      return { open: (l + r) / 2 < EYE_BLINK_MAX };
    }

    function getBoundingBox(landmarks) {
      let minX = 1, maxX = 0, minY = 1, maxY = 0;
      for (const p of landmarks) {
        if (p.x < minX) minX = p.x;
        if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.y > maxY) maxY = p.y;
      }
      return {
        widthFrac:   maxX - minX,
        centerXFrac: (minX + maxX) / 2,
        centerYFrac: (minY + maxY) / 2,
      };
    }

    function evaluateChecks(faceLandmarks, faceBlendshapes) {
      if (!faceLandmarks?.length) {
        return { faceDetected: false, centered: false, distance: false, eyesOpen: false };
      }
      const bbox = getBoundingBox(faceLandmarks[0]);
      const eye  = getEyeOpenness(faceBlendshapes);
      return {
        faceDetected: true,
        centered:  Math.abs(bbox.centerXFrac - 0.5) < CENTER_TOLERANCE &&
                   Math.abs(bbox.centerYFrac - 0.5) < CENTER_TOLERANCE,
        distance:  bbox.widthFrac >= DISTANCE_MIN && bbox.widthFrac <= DISTANCE_MAX,
        eyesOpen:  eye.open,
        _bbox: bbox,
      };
    }

    // ── CheckItem UI ─────────────────────────────────────────────────────
    function CheckItem({ label, ok }) {
      return React.createElement('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '6px 0',
          transition: 'opacity 0.2s',
          opacity: ok ? 1 : 0.55,
        }
      },
        React.createElement('div', {
          style: {
            width: '20px', height: '20px', borderRadius: '50%', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: ok ? '#22c55e' : '#e5e7eb',
            transition: 'background 0.25s ease',
            position: 'relative',
          }
        },
          ok && React.createElement('div', { className: 'check-ring' }),
          ok
            ? React.createElement('svg', { width:10, height:10, fill:'none', stroke:'white',
                strokeWidth:2.5, viewBox:'0 0 24 24' },
                React.createElement('path', { strokeLinecap:'round', strokeLinejoin:'round', d:'M5 13l4 4L19 7' })
              )
            : React.createElement('div', {
                style: { width:6, height:6, borderRadius:'50%', background:'#9ca3af' }
              })
        ),
        React.createElement('span', {
          style: { fontSize:'13px', color: ok ? '#111' : '#9ca3af',
                   fontWeight: ok ? 500 : 400, transition:'color 0.25s' }
        }, label)
      );
    }

    // ── Main component ────────────────────────────────────────────────────
    function LiveCapture() {
      const videoRef          = useRef(null);
      const canvasRef         = useRef(null);
      const rafRef            = useRef(null);
      const holdCountRef      = useRef(0);   // good frames accumulated
      const cancelCountRef    = useRef(0);   // bad frames during countdown
      const countdownRef      = useRef(null);// setInterval handle

      const { landmarker, loadError } = useFaceLandmarker();

      const [stream,    setStream]    = useState(null);
      const [phase,     setPhase]     = useState('loading');
      // loading | live | holding | counting | done | error
      const [checks,    setChecks]    = useState({ faceDetected:false, centered:false, distance:false, eyesOpen:false });
      const [hint,      setHint]      = useState('');
      const [countdown, setCountdown] = useState(null);

      const allGood = checks.faceDetected && checks.centered && checks.distance && checks.eyesOpen;

      // ── Camera start ──
      const startCamera = useCallback(async () => {
        try {
          const s = await navigator.mediaDevices.getUserMedia({
            video: { facingMode:'user', width:640, height:480 }, audio:false,
          });
          setStream(s);
          if (videoRef.current) { videoRef.current.srcObject = s; await videoRef.current.play(); }
          setPhase('live');
        } catch {
          setPhase('error');
        }
      }, []);

      useEffect(() => {
        if (landmarker && phase === 'loading') startCamera();
      }, [landmarker, phase, startCamera]);

      useEffect(() => () => {
        stream?.getTracks().forEach(t => t.stop());
        if (rafRef.current)     cancelAnimationFrame(rafRef.current);
        if (countdownRef.current) clearInterval(countdownRef.current);
      }, [stream]);

      // ── Capture ──
      const capture = useCallback(() => {
        const video = videoRef.current, canvas = canvasRef.current;
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.translate(canvas.width, 0); ctx.scale(-1, 1);
        ctx.drawImage(video, 0, 0);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.92);

        stream?.getTracks().forEach(t => t.stop()); setStream(null);
        cancelAnimationFrame(rafRef.current);
        setPhase('done');
        window.dispatchEvent(new CustomEvent('livecapture:captured', { detail: { dataUrl } }));
      }, [stream]);

      // ── Countdown (with real-time face guard) ──
      const beginCountdown = useCallback(() => {
        setPhase('counting');
        cancelCountRef.current = 0;
        let remaining = COUNTDOWN_SECONDS;
        setCountdown(remaining);

        countdownRef.current = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(countdownRef.current);
            setCountdown(null);
            capture();
          } else {
            setCountdown(remaining);
          }
        }, 1000);
      }, [capture]);

      // Cancel countdown and go back to live detection
      const cancelCountdown = useCallback((reason) => {
        clearInterval(countdownRef.current);
        countdownRef.current = null;
        cancelCountRef.current = 0;
        holdCountRef.current   = 0;
        setCountdown(null);
        setPhase('live');
        setHint(reason);
      }, []);

      // ── Detection loop (runs in 'live' AND 'counting' phases) ──
      useEffect(() => {
        if ((phase !== 'live' && phase !== 'counting' && phase !== 'holding') || !landmarker) return;
        let active = true;

        function tick() {
          if (!active) return;
          const video = videoRef.current;

          if (video?.readyState >= 2) {
            const result = landmarker.detectForVideo(video, performance.now());
            const c = evaluateChecks(result.faceLandmarks, result.faceBlendshapes);
            const good = c.faceDetected && c.centered && c.distance && c.eyesOpen;

            if (phase === 'counting') {
              // During countdown: if face fails, accumulate bad frames then cancel
              if (!good) {
                cancelCountRef.current += 1;
                if (cancelCountRef.current >= CANCEL_FRAMES_REQUIRED) {
                  cancelCountdown(
                    !c.faceDetected ? 'Face lost — restarting'
                    : !c.centered   ? 'Stay centered — restarting'
                    : !c.distance   ? 'Hold your distance — restarting'
                    :                 'Keep eyes open — restarting'
                  );
                }
              } else {
                cancelCountRef.current = 0;
              }
              rafRef.current = requestAnimationFrame(tick);
              return;
            }

            // live / holding phase
            setChecks(c);

            if (!c.faceDetected)  setHint('Look directly at the camera');
            else if (!c.centered) setHint('Center your face in the frame');
            else if (c._bbox?.widthFrac < DISTANCE_MIN) setHint('Move a little closer');
            else if (c._bbox?.widthFrac > DISTANCE_MAX) setHint('Move back slightly');
            else if (!c.eyesOpen) setHint('Keep your eyes open');
            else if (good)        setHint('');

            if (good) {
              holdCountRef.current += 1;
              if (holdCountRef.current >= HOLD_FRAMES_REQUIRED) {
                holdCountRef.current = 0;
                beginCountdown();
                return;
              }
            } else {
              holdCountRef.current = 0;
            }
          }

          rafRef.current = requestAnimationFrame(tick);
        }

        rafRef.current = requestAnimationFrame(tick);
        return () => {
          active = false;
          cancelAnimationFrame(rafRef.current);
        };
      }, [phase, landmarker, beginCountdown, cancelCountdown]);

      // ── "Hold still" bar — how full is holdCountRef as a % ──
      const holdProgress = phase === 'live' && allGood
        ? Math.min((holdCountRef.current / HOLD_FRAMES_REQUIRED) * 100, 100)
        : 0;

      if (loadError) return React.createElement('div', {
        style:{ padding:'40px 24px', textAlign:'center', color:'#ef4444', fontSize:'14px' }
      }, 'Face detection failed to load. Please refresh and try again.');

      // ── Oval border color ──
      const ovalColor = phase === 'counting' ? '#6a3df5'
                      : allGood              ? '#22c55e'
                      :                        'rgba(255,255,255,0.5)';
      const ovalGlow  = phase === 'counting' ? '0 0 0 3px rgba(106,61,245,0.25)'
                      : allGood              ? '0 0 0 3px rgba(34,197,94,0.2)'
                      :                        'none';

      return React.createElement('div', { style:{ width:'100%' } },

        // ── Camera viewport ──
        React.createElement('div', {
          style:{ position:'relative', background:'#000', width:'100%', aspectRatio:'4/3' }
        },
          React.createElement('video', {
            ref: videoRef,
            style:{ width:'100%', height:'100%', objectFit:'cover', transform:'scaleX(-1)', display:'block' },
            muted: true, playsInline: true,
          }),
          React.createElement('canvas', { ref: canvasRef, style:{ display:'none' } }),

          // Dark gradient bottom (so checklist text sits on clean bg)
          React.createElement('div', {
            style:{
              position:'absolute', bottom:0, left:0, right:0, height:'35%',
              background:'linear-gradient(to top, rgba(0,0,0,0.55), transparent)',
              pointerEvents:'none',
            }
          }),

          // Oval face guide
          React.createElement('div', {
            style:{
              position:'absolute', inset:0,
              display:'flex', alignItems:'center', justifyContent:'center',
              pointerEvents:'none',
            }
          },
            React.createElement('div', {
              style:{
                width:'160px', height:'210px', borderRadius:'50%',
                border:`3px solid ${ovalColor}`,
                boxShadow: ovalGlow,
                transition:'border-color 0.3s, box-shadow 0.3s',
              }
            })
          ),

          // Hint text inside frame (bottom center)
          (phase === 'live' || phase === 'counting') && hint &&
            React.createElement('div', {
              style:{
                position:'absolute', bottom:'16px', left:0, right:0,
                textAlign:'center', pointerEvents:'none',
              }
            },
              React.createElement('span', {
                className: 'animate-fade',
                style:{
                  display:'inline-block',
                  background:'rgba(0,0,0,0.55)', color:'#fff',
                  fontSize:'12px', fontWeight:500, padding:'5px 12px',
                  borderRadius:'20px', backdropFilter:'blur(4px)',
                }
              }, hint)
            ),

          // Countdown overlay
          phase === 'counting' && countdown !== null &&
            React.createElement('div', {
              style:{
                position:'absolute', inset:0,
                display:'flex', alignItems:'center', justifyContent:'center',
                background:'rgba(0,0,0,0.35)',
              }
            },
              React.createElement('span', {
                className: 'animate-pop',
                key: countdown,
                style:{
                  fontSize:'80px', fontWeight:700, color:'#fff',
                  lineHeight:1, textShadow:'0 2px 20px rgba(0,0,0,0.5)',
                  display:'block',
                }
              }, countdown)
            ),

          // Loading overlay
          phase === 'loading' &&
            React.createElement('div', {
              style:{
                position:'absolute', inset:0, display:'flex', flexDirection:'column',
                alignItems:'center', justifyContent:'center', background:'rgba(0,0,0,0.75)',
              }
            },
              React.createElement('div', {
                style:{
                  width:'30px', height:'30px', borderRadius:'50%',
                  border:'3px solid rgba(255,255,255,0.2)',
                  borderTop:'3px solid #fff',
                  animation:'spin 0.8s linear infinite', marginBottom:'12px',
                }
              }),
              React.createElement('p', { style:{ color:'rgba(255,255,255,0.7)', fontSize:'13px', margin:0 } },
                'Starting camera...')
            ),

          // Error overlay
          phase === 'error' &&
            React.createElement('div', {
              style:{
                position:'absolute', inset:0, display:'flex', flexDirection:'column',
                alignItems:'center', justifyContent:'center',
                background:'rgba(0,0,0,0.8)', padding:'24px', textAlign:'center',
              }
            },
              React.createElement('p', { style:{ color:'#fff', fontWeight:600, fontSize:'15px', margin:'0 0 6px' } },
                'Camera unavailable'),
              React.createElement('p', { style:{ color:'rgba(255,255,255,0.6)', fontSize:'13px', margin:0 } },
                'Allow camera access in your browser and refresh.')
            )
        ),

        // ── Bottom panel ──
        React.createElement('div', { style:{ padding:'18px 20px 20px' } },

          // Checklist — 2×2 grid
          React.createElement('div', {
            style:{
              display:'grid', gridTemplateColumns:'1fr 1fr',
              gap:'0 8px',
            }
          },
            React.createElement(CheckItem, { label:'Face detected',    ok: checks.faceDetected }),
            React.createElement(CheckItem, { label:'Face centered',    ok: checks.centered }),
            React.createElement(CheckItem, { label:'Correct distance', ok: checks.distance }),
            React.createElement(CheckItem, { label:'Eyes visible',     ok: checks.eyesOpen }),
          ),

          // "Hold still" progress bar (only shown when all checks pass, before countdown)
          React.createElement('div', {
            style:{
              marginTop:'14px', height:'3px', borderRadius:'99px',
              background:'#f0f0f0', overflow:'hidden',
              opacity: (phase === 'live' && allGood) ? 1 : 0,
              transition:'opacity 0.2s',
            }
          },
            React.createElement('div', {
              style:{
                height:'100%', borderRadius:'99px',
                background:'linear-gradient(90deg,#6a3df5,#4b8bff)',
                width: `${holdProgress}%`,
                transition:'width 0.05s linear',
              }
            })
          ),

          // Status line below bar
          React.createElement('p', {
            style:{
              textAlign:'center', fontSize:'12px', margin:'10px 0 0',
              color: phase === 'counting' ? '#6a3df5'
                   : allGood             ? '#22c55e'
                   :                       '#bbb',
              fontWeight: 500,
              minHeight:'16px',
            }
          },
            phase === 'counting' ? 'Capturing — hold still...'
            : allGood            ? 'Hold still...'
            : 'Waiting for all checks to pass'
          )
        )
      );
    }

    window.mountLiveCapture = function (rootId) {
      const root = ReactDOM.createRoot(document.getElementById(rootId));
      root.render(React.createElement(LiveCapture));
    };

  })();