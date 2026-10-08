import {mkdir,copyFile,readdir} from 'node:fs/promises';
await mkdir('dist/src',{recursive:true});
await copyFile('index.html','dist/index.html');
for(const name of await readdir('public'))await copyFile('public/'+name,'dist/'+name); // app manifest and icons
for(const name of await readdir('src'))if(/\.(js|css)$/.test(name))await copyFile('src/'+name,'dist/src/'+name);
process.stdout.write('Static production build complete; runtime OIDC configuration remains external.\n');
