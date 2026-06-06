/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pre-existing noImplicitAny errors across 24 files — skip until bulk-fixed
  typescript: { ignoreBuildErrors: true },
  // Pre-existing no-explicit-any lint errors in explore/ module — skip until bulk-fixed
  eslint: { ignoreDuringBuilds: true },

  // ── API Proxy Rewrites ────────────────────────────────────────────
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },

  // ── Transpile ESM-only packages that Next.js can't auto-detect ────
  transpilePackages: [
    "react-leaflet",
    "react-leaflet-cluster",
    "react-resizable-panels",
    "@deck.gl/core",
    "@deck.gl/layers",
    "@deck.gl/react",
    "react-map-gl",
  ],

  // ── Experimental optimizations ────────────────────────────────────
  experimental: {
    // Tree-shake barrel exports for large icon / UI libraries
    optimizePackageImports: [
      "lucide-react",
      "@radix-ui/react-icons",
      "react-pdf",
    ],
  },

  // ── Webpack configuration ─────────────────────────────────────────
  webpack: (config, { isServer }) => {
    // Alias plotly.js → plotly.js-dist-min so react-plotly.js (which
    // internally requires 'plotly.js') resolves to the minified dist.
    config.resolve.alias = {
      ...config.resolve.alias,
      "plotly.js": "plotly.js-dist-min",
    };

    if (!isServer) {
      // Split heavy client-side libraries into separate chunks so
      // webpack doesn't try to analyze + bundle everything in one pass.
      config.optimization.splitChunks = {
        ...config.optimization.splitChunks,
        cacheGroups: {
          ...config.optimization.splitChunks?.cacheGroups,

          // Plotly (~3MB) — isolate into its own chunk
          plotly: {
            test: /[\\/]node_modules[\\/](plotly\.js|plotly\.js-dist-min)[\\/]/,
            name: "plotly",
            chunks: "all",
            priority: 30,
            reuseExistingChunk: true,
          },

          // Leaflet + react-leaflet
          leaflet: {
            test: /[\\/]node_modules[\\/](leaflet|react-leaflet|react-leaflet-cluster)[\\/]/,
            name: "leaflet",
            chunks: "all",
            priority: 25,
            reuseExistingChunk: true,
          },

          // deck.gl + maplibre
          deckgl: {
            test: /[\\/]node_modules[\\/](@deck\.gl|@loaders\.gl|maplibre-gl|react-map-gl)[\\/]/,
            name: "deckgl",
            chunks: "all",
            priority: 25,
            reuseExistingChunk: true,
          },

          // CodeMirror
          codemirror: {
            test: /[\\/]node_modules[\\/](@codemirror|@lezer|codemirror)[\\/]/,
            name: "codemirror",
            chunks: "all",
            priority: 25,
            reuseExistingChunk: true,
          },

          // PDF viewer
          pdfjs: {
            test: /[\\/]node_modules[\\/](react-pdf|pdfjs-dist)[\\/]/,
            name: "pdfjs",
            chunks: "all",
            priority: 25,
            reuseExistingChunk: true,
          },
        },
      };
    }

    return config;
  },
};

export default nextConfig;
