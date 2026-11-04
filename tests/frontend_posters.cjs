const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('backend/static/app.js','utf8');
const context=vm.createContext({URL,document:{createElement:tag=>({tag})}});
vm.runInContext(source.slice(source.indexOf('function safeUrl('),source.indexOf('function normalize(')),context);
const image=vm.runInContext("posterImage('https://images.example/poster.jpg','Название')",context);
assert.equal(image.src,'https://images.example/poster.jpg');assert.equal(image.loading,'lazy');
image.onerror();assert.equal(image.src,'/static/images/poster-unavailable.svg');assert.equal(image.hidden,false);
image.onerror();assert.equal(image.hidden,true); // A broken local asset cannot cause a retry loop.
for(const value of [null,'javascript:alert(1)','https://user:password@example.com/poster.jpg',
 'https://shikimori.io/assets/globals/missing_original.jpg',
 'https://shikimori.one/assets/globals/missing_preview.jpg?version=2']){
 context.value=value;
 const result=vm.runInContext("posterImage(value,'Название')",context);
 assert.equal(result.src,'/static/images/poster-unavailable.svg');
}
context.image=image;
vm.runInContext("setPosterImage(image,'https://images.example/new.jpg','Новое',false)",context);
assert.equal(image.hidden,false);assert.equal(image.loading,'eager');assert.equal(image.alt,'Новое');
image.onerror();assert.equal(image.src,'/static/images/poster-unavailable.svg');assert.equal(image.hidden,false);
console.log('Posters UI: missing-image JPEGs, absent/unsafe URLs, HTTP failures, bounded fallback and reused detail images OK');
