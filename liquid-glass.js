/* ──────────────────────────────────────────────────────────────────────────
   Full-fidelity liquid glass effect using WebGL.
   Renders a displacement/refraction pass over the page background,
   then composites per .glass-card element with rounded-rect clipping.

   Technique:
   1. Every animation frame, take a snapshot of the flat background
      (blobs only, rendered offscreen) into a WebGL texture.
   2. Run a refraction fragment shader that uses a time-driven
      normal-map distortion (simulated via multi-octave sine waves)
      to offset UV lookups — producing a wobbly wet-glass look.
   3. Clip the output to the bounding rectangles of all .glass-card
      elements so only those surfaces refract.
   4. Overlay a specular highlight pass (Phong-like) in the same shader.
────────────────────────────────────────────────────────────────────────── */

(function () {
    'use strict';

    // ── Config ──────────────────────────────────────────────────────────────
    const CFG = {
        refractStrength: 0.018, // how much UV is displaced (0–0.05)
        specularPower: 28, // shininess of highlight
        specularAmt: 0.38, // intensity of specular
        rimAmt: 0.22, // edge iridescence brightness
        speed: 0.28, // animation speed multiplier
        tintR: 0.80, // liquid tint (mint green)
        tintG: 1.00,
        tintB: 0.85,
        tintAlpha: 0.10, // how much tint bleeds in
    };

    // ── Vertex shader ────────────────────────────────────────────────────────
    const VERT = `
    attribute vec2 a_pos;
    varying   vec2 v_uv;
    void main(){
      v_uv = a_pos * 0.5 + 0.5;
      gl_Position = vec4(a_pos, 0.0, 1.0);
    }
  `;

    // ── Fragment shader ──────────────────────────────────────────────────────
    const FRAG = `
    precision mediump float;

    uniform sampler2D u_bg;       // background snapshot
    uniform float     u_time;
    uniform vec2      u_res;      // canvas resolution
    uniform float     u_strength; // refraction strength
    uniform float     u_specPow;
    uniform float     u_specAmt;
    uniform float     u_rimAmt;
    uniform vec3      u_tint;
    uniform float     u_tintA;

    // rect list (max 8 cards): xy=topLeft normalised, zw=bottomRight normalised
    uniform vec4  u_rects[8];
    uniform int   u_rectCount;
    uniform vec4  u_radii[8];     // x=radius normalised (uniform corner)

    varying vec2 v_uv;

    // ── helpers ──────────────────────────────────────────────────────────
    float sdRoundBox(vec2 p, vec2 b, float r){
      vec2 q = abs(p) - b + r;
      return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
    }

    // FBM-style displacement normal
    vec2 distortUV(vec2 uv, float t){
      float s1 = sin(uv.x * 6.2  + t * 1.1) * cos(uv.y * 5.8  + t * 0.9);
      float s2 = sin(uv.x * 11.4 - t * 0.7) * sin(uv.y * 9.3  + t * 1.3);
      float s3 = cos(uv.x * 8.1  + t * 1.5) * cos(uv.y * 12.7 - t * 0.5);
      float dx = (s1 * 0.50 + s2 * 0.30 + s3 * 0.20);
      float dy = (s1 * 0.20 + s2 * 0.50 + s3 * 0.30);
      return vec2(dx, dy);
    }

    void main(){
      // Default: fully transparent (pass-through)
      gl_FragColor = vec4(0.0);

      float t = u_time * ${CFG.speed.toFixed(3)};
      bool insideAny = false;
      float closestDist = 1e9;
      int   hit = -1;

      // ── find which card we're inside ────────────────────────────────────
      for(int i = 0; i < 8; i++){
        if(i >= u_rectCount) break;
        vec4 r  = u_rects[i];
        float rad = u_radii[i].x;
        vec2 centre = (r.xy + r.zw) * 0.5;
        vec2 half   = (r.zw - r.xy) * 0.5;
        float d = sdRoundBox(v_uv - centre, half, rad);
        if(d < 0.0){
          insideAny = true;
          if(d < closestDist){ closestDist = d; hit = i; }
        }
      }

      if(!insideAny) return;

      // ── distortion ──────────────────────────────────────────────────────
      vec2 disp   = distortUV(v_uv, t) * u_strength;
      vec2 refUV  = v_uv + disp;
      refUV = clamp(refUV, 0.002, 0.998);

      // Flip Y for texture (canvas top-left vs GL bottom-left)
      vec2 bgUV = vec2(refUV.x, 1.0 - refUV.y);
      vec4 bg   = texture2D(u_bg, bgUV);

      // ── specular highlight ───────────────────────────────────────────────
      // Fake light at top-left; normal derived from displacement gradient
      vec2 eps = vec2(0.002, 0.0);
      vec2 dRight = distortUV(v_uv + eps,       t);
      vec2 dUp    = distortUV(v_uv + eps.yx,    t);
      vec3 norm = normalize(vec3(dRight - disp, eps.x * 80.0));
      vec3 lightDir = normalize(vec3(-0.6, 0.8, 1.0));
      float spec = pow(max(dot(norm, lightDir), 0.0), u_specPow) * u_specAmt;

      // ── rim / edge iridescence ───────────────────────────────────────────
      // Brighter as we approach the edge of the card SDF
      vec4 rect = u_rects[hit];
      float rad = u_radii[hit].x;
      vec2 ctr  = (rect.xy + rect.zw) * 0.5;
      vec2 half = (rect.zw - rect.xy) * 0.5;
      float rimD = sdRoundBox(v_uv - ctr, half, rad);
      float rimF = smoothstep(-0.010, 0.0, rimD); // 0=centre, 1=edge
      float iridShift = sin(v_uv.x * 18.0 - t * 2.0) * 0.5 + 0.5;
      vec3 irid = mix(vec3(0.7,1.0,0.8), vec3(0.85,0.92,1.0), iridShift);
      float rim = rimF * u_rimAmt;

      // ── tint ─────────────────────────────────────────────────────────────
      vec3 col = bg.rgb;
      col = mix(col, u_tint, u_tintA);
      col += spec;
      col += irid * rim;
      col = clamp(col, 0.0, 1.0);

      // ── edge alpha (soft outer AA) ────────────────────────────────────────
      float alpha = smoothstep(0.002, -0.001, closestDist);
      // Inner transparency – centre of card is more see-through
      float innerOpacity = 0.72 + rimF * 0.20;

      gl_FragColor = vec4(col, alpha * innerOpacity);
    }
  `;

    // ── GL helpers ───────────────────────────────────────────────────────────
    function compile(gl, type, src) {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
            throw new Error('Shader compile: ' + gl.getShaderInfoLog(s));
        return s;
    }

    function createProgram(gl) {
        const p = gl.createProgram();
        gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VERT));
        gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, FRAG));
        gl.linkProgram(p);
        if (!gl.getProgramParameter(p, gl.LINK_STATUS))
            throw new Error('Program link: ' + gl.getProgramInfoLog(p));
        return p;
    }

    // ── Main init ────────────────────────────────────────────────────────────
    function init() {
        // Create & position canvas
        const canvas = document.createElement('canvas');
        canvas.id = 'distortion-canvas';
        document.body.insertBefore(canvas, document.body.firstChild);

        const gl = canvas.getContext('webgl', {
            alpha: true,
            premultipliedAlpha: false
        });
        if (!gl) {
            console.warn('LiquidGlass: WebGL not supported');
            return;
        }

        // Fullscreen quad
        const buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

        const prog = createProgram(gl);
        gl.useProgram(prog);

        const aPos = gl.getAttribLocation(prog, 'a_pos');
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

        // Uniforms
        const U = {};
        ['u_bg', 'u_time', 'u_res', 'u_strength', 'u_specPow', 'u_specAmt',
            'u_rimAmt', 'u_tint', 'u_tintA', 'u_rectCount'
        ].forEach(n => {
            U[n] = gl.getUniformLocation(prog, n);
        });
        const uRects = Array.from({
            length: 8
        }, (_, i) => gl.getUniformLocation(prog, `u_rects[${i}]`));
        const uRadii = Array.from({
            length: 8
        }, (_, i) => gl.getUniformLocation(prog, `u_radii[${i}]`));

        // Background texture (updated each frame from an offscreen canvas)
        const bgTex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, bgTex);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

        // Offscreen canvas to snapshot background (blobs only)
        const offscreen = document.createElement('canvas');
        const offCtx = offscreen.getContext('2d');

        // Blend
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

        // ── Resize ──────────────────────────────────────────────────────────────
        function resize() {
            const dpr = window.devicePixelRatio || 1;
            canvas.width = window.innerWidth * dpr;
            canvas.height = window.innerHeight * dpr;
            canvas.style.width = window.innerWidth + 'px';
            canvas.style.height = window.innerHeight + 'px';
            offscreen.width = canvas.width;
            offscreen.height = canvas.height;
            gl.viewport(0, 0, canvas.width, canvas.height);
        }
        resize();
        window.addEventListener('resize', resize);

        // ── Collect card rects ──────────────────────────────────────────────────
        function getCardRects() {
            const dpr = window.devicePixelRatio || 1;
            const W = canvas.width,
                H = canvas.height;
            const cards = document.querySelectorAll('.glass-card');
            const rects = [],
                radii = [];
            cards.forEach(el => {
                const r = el.getBoundingClientRect();
                // Normalise to 0–1
                rects.push([r.left / window.innerWidth, r.top / window.innerHeight,
                    r.right / window.innerWidth, r.bottom / window.innerHeight
                ]);
                // Get border-radius from style (CSS var --radius-xl = 36px)
                const cs = getComputedStyle(el);
                const rad = parseFloat(cs.borderRadius) || 36;
                radii.push(rad / window.innerWidth); // normalise by width
            });
            return {
                rects,
                radii
            };
        }

        // ── Snapshot background blobs into texture ──────────────────────────────
        function captureBackground() {
            // Hide glass cards, snapshot, restore
            const cards = document.querySelectorAll('.glass-card, .app-shell');
            cards.forEach(el => el.style.visibility = 'hidden');

            // Use html2canvas-style trick: draw body background
            offCtx.clearRect(0, 0, offscreen.width, offscreen.height);

            // Draw the gradient background
            const grd = offCtx.createLinearGradient(0, 0, offscreen.width, offscreen.height);
            grd.addColorStop(0, '#e8f5ee');
            grd.addColorStop(1, '#d4f0e0');
            offCtx.fillStyle = grd;
            offCtx.fillRect(0, 0, offscreen.width, offscreen.height);

            // Draw the animated blobs (read their current positions from DOM)
            const blobs = document.querySelectorAll('.bg-blob');
            blobs.forEach(blob => {
                const r = blob.getBoundingClientRect();
                const dpr = window.devicePixelRatio || 1;
                const cs = getComputedStyle(blob);
                const bg = cs.backgroundColor || cs.background;

                // Parse hex blob colour from css var → approximate
                offCtx.save();
                offCtx.filter = `blur(${parseFloat(cs.filter?.match(/blur\(([^)]+)\)/)?.[1]) || 70}px)`;

                // Use the blob's background as fill (extract from inline style)
                offCtx.beginPath();
                offCtx.ellipse(
                    (r.left + r.width / 2) * dpr,
                    (r.top + r.height / 2) * dpr,
                    r.width / 2 * dpr,
                    r.height / 2 * dpr,
                    0, 0, Math.PI * 2
                );
                offCtx.fillStyle = bg.includes('gradient') ? '#ccffcc88' : bg;
                offCtx.fill();
                offCtx.restore();
            });

            cards.forEach(el => el.style.visibility = '');

            gl.bindTexture(gl.TEXTURE_2D, bgTex);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, offscreen);
        }

        // ── Render loop ──────────────────────────────────────────────────────────
        let frameCount = 0;

        function frame(ts) {
            requestAnimationFrame(frame);

            // Capture background every 3 frames (performance)
            frameCount++;
            if (frameCount % 3 === 0) captureBackground();

            const t = ts * 0.001;
            const {
                rects,
                radii
            } = getCardRects();
            const count = Math.min(rects.length, 8);

            gl.clear(gl.COLOR_BUFFER_BIT);

            gl.uniform1i(U.u_bg, 0);
            gl.uniform1f(U.u_time, t);
            gl.uniform2f(U.u_res, canvas.width, canvas.height);
            gl.uniform1f(U.u_strength, CFG.refractStrength);
            gl.uniform1f(U.u_specPow, CFG.specularPower);
            gl.uniform1f(U.u_specAmt, CFG.specularAmt);
            gl.uniform1f(U.u_rimAmt, CFG.rimAmt);
            gl.uniform3f(U.u_tint, CFG.tintR, CFG.tintG, CFG.tintB);
            gl.uniform1f(U.u_tintA, CFG.tintAlpha);
            gl.uniform1i(U.u_rectCount, count);

            for (let i = 0; i < count; i++) {
                gl.uniform4fv(uRects[i], rects[i]);
                gl.uniform4f(uRadii[i], radii[i], 0, 0, 0);
            }

            gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        }

        requestAnimationFrame(frame);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();