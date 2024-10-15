// vite.config.ts
import { resolve
} from 'path'
import { defineConfig
} from 'vite'

export default defineConfig
({
 build: {
   lib: {
     // Could also be a dictionary or array of multiple entry points
     entry: resolve(__dirname, 'src/main.ts'),
     name: 'PotatoLib',
     // the proper extensions will be added
     fileName: 'potato',
   },
   rollupOptions: {
     // make sure to externalize deps that shouldn't be bundled
     // into your library
     external: ['vue'],
     output: {
       // Provide global variables to use in the UMD build
       // for externalized deps
       dir: "live",
       globals: {
         vue: 'Vue',
       },
     },
   },
 },
})