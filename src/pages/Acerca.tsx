import { useEffect } from "react";
import { BRAND_NAME, PANEL_URL, PETITION_URL, PRIVACY_URL, TERMS_URL } from "../config";
import { TopBar } from "../components/TopBar";
import { useSession } from "../lib/hooks";
import { Link } from "../router";

/** WebP copies made at build prep (public/img/<name>-640.webp and -1080.webp, 12 to 130 KB). */
function photo(name: string, w: number) {
  return `/img/${name}-${w}.webp`;
}

function Photo({ name, alt, className = "" }: { name: string; alt: string; className?: string }) {
  return (
    <img
      src={photo(name, 640)}
      srcSet={`${photo(name, 640)} 640w, ${photo(name, 1080)} 1080w`}
      sizes="(min-width: 768px) 50vw, 100vw"
      alt={alt}
      loading="lazy"
      decoding="async"
      width={640}
      height={400}
      className={`h-full w-full bg-panel-2 object-cover ${className}`}
    />
  );
}

const TARGETS = [
  {
    img: "draga",
    alt: "Draga minera de madera y metal trabajando en la orilla del río Madre de Dios",
    title: "Dragas y balsas en los ríos",
    text: "Embarcaciones pequeñas que succionan el lecho del río para separar el oro. El radar satelital las distingue sobre el agua incluso con nubes, de día o de noche.",
  },
  {
    img: "tajo",
    alt: "Imagen satelital de La Pampa, Madre de Dios: grandes manchas de bosque destruido y pozas mineras junto al río",
    title: "Minería de tajo abierto",
    text: "Bosque removido, pozas y suelo expuesto que aparecen de una semana a otra. Comparamos imágenes recientes para encontrar cada nuevo frente minero.",
  },
];

const STEPS = [
  { title: "Revisamos el satélite", text: "Cada nueva imagen de los ríos y bosques de tu región pasa por nuestro sistema." },
  { title: "Encontramos la actividad", text: "Marcamos posibles dragas y tajos nuevos con su ubicación y la fecha de la imagen." },
  { title: "Te avisamos por WhatsApp", text: "Si pasa en la zona que elegiste, te llega el aviso con el punto en el mapa." },
];

const DECISIONS = [
  "Usamos el radar Sentinel-1, que pasa cada 2 a 6 días y atraviesa las nubes. Solo sirve en ríos anchos.",
  "Las balsas en ríos de menos de 30 m de ancho no se ven con datos gratuitos. Hoy quedan fuera.",
  "La mejora es el radar pagado (ICEYE), con imágenes en menos de un día pero con costo por escena.",
  "Los dos eventos de ayer en el río Yaguas son escenas de prueba del detector; movimos su fecha a ayer para la demostración. La escena de hoy entra en vivo.",
  "El detector corre cuando lo llamamos al terminar de subir las imágenes, no con cada archivo: el bucket avisa archivo por archivo y no sabe cuándo terminó la carga.",
  "Alertamos por WhatsApp y no con una app: los equipos de campo ya lo usan y llega con poca señal.",
  "Durante el hackathon enviamos como máximo 50 alertas y solo de escenas de hoy o ayer, para que una prueba no le escriba a nadie de más.",
  "El detector se entrenó, y los eventos de demostración se produjeron, con imágenes de Planet y SkyFi obtenidas a través de un aliado con acceso licenciado.",
  "Entrar desde el enlace de una alerta de WhatsApp dura 7 días; después se pide el código otra vez.",
  "La API no tiene cola de tareas: las alertas salen en un hilo después de guardar la escena, y si una falla un comando la reintenta.",
  "Este sitio está hecho para funcionar en los celulares más lentos y con la peor señal: primero el texto, el mapa después.",
];

const PHOTO_CREDITS = [
  {
    text: "río Madre de Dios por Murray Foubister",
    license: "CC BY-SA 2.0",
    href: "https://commons.wikimedia.org/wiki/File:Flight_from_Cusco_to_Puerto_Moldinado%E2%80%A6Rio_Madre_de_Dios_(8445823960).jpg",
  },
  {
    text: "draga en el río Madre de Dios por USDA Forest Service",
    license: "dominio público",
    href: "https://commons.wikimedia.org/wiki/File:Gold_Suction_Dredge_-_Madre_de_Dios_River_(8183089237).jpg",
  },
  {
    text: "minería en Madre de Dios, imagen satelital de INPE",
    license: "CC BY-SA 2.0",
    href: "https://commons.wikimedia.org/wiki/File:Garimpo_de_ouro_ilegal_na_Amaz%C3%B4nia_em_Madre_de_Dios,_Per%C3%BA.jpg",
  },
];

const btnPrimary = "inline-flex min-h-12 items-center justify-center rounded-lg bg-rojo px-5 font-bold text-white hover:bg-rojo-2";
const btnOutline = "inline-flex min-h-12 items-center justify-center rounded-lg border border-line px-5 font-bold hover:bg-panel";

export default function Acerca() {
  const session = useSession();
  useEffect(() => {
    const prev = document.title;
    document.title = `Acerca · ${BRAND_NAME}`;
    return () => {
      document.title = prev;
    };
  }, []);

  const cta = session ? (
    <Link href={PANEL_URL} className={btnPrimary}>
      Abrir Mi panel
    </Link>
  ) : (
    <Link href="/entrar" className={btnPrimary}>
      Entrar a {BRAND_NAME}
    </Link>
  );

  return (
    <div className="min-h-dvh">
      <TopBar />

      <section className="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-4 pb-12 pt-8 sm:px-6 lg:grid-cols-2 lg:items-center lg:gap-14 lg:py-16 [&>*]:min-w-0">
        <div>
          <p className="label-caps">Vigilancia satelital de ríos</p>
          <h1 className="mt-2 text-[2.25rem] font-black leading-[1.05] tracking-tight sm:text-5xl">
            Vigilamos la <span className="text-rojo">minería ilegal</span> en la Amazonía.
          </h1>
          <p className="mt-4 text-lg text-muted">Dragas y tajos abiertos, detectados por satélite. Te avisamos al instante por WhatsApp.</p>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <Link href="/" className={btnPrimary}>
              Ver el mapa
            </Link>
            <a href="#como-funciona" className={btnOutline}>
              Cómo funciona
            </a>
          </div>
          <a href={PETITION_URL} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex min-h-11 items-center font-bold text-rojo underline underline-offset-4">
            Firma la petición por alertas satelitales
          </a>
        </div>
        <div className="aspect-[16/10] overflow-hidden rounded-xl border border-line">
          <Photo name="rio" alt="Vista aérea del río Madre de Dios atravesando la selva amazónica" />
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:py-16">
          <h2 className="text-3xl font-black tracking-tight">¿Qué detecta {BRAND_NAME}?</h2>
          <p className="mt-3 max-w-2xl text-lg text-muted">Dos formas de minería ilegal de oro que dejan huella visible desde el espacio.</p>
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            {TARGETS.map((t) => (
              <article key={t.title} className="overflow-hidden rounded-xl border border-line bg-panel">
                <div className="aspect-[16/10]">
                  <Photo name={t.img} alt={t.alt} />
                </div>
                <div className="p-5">
                  <h3 className="text-xl font-bold">{t.title}</h3>
                  <p className="mt-2 text-muted">{t.text}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="como-funciona" className="scroll-mt-16 border-t border-line bg-panel">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:py-16">
          <h2 className="text-3xl font-black tracking-tight">¿Cómo funciona?</h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex gap-4">
                <span className="tnum grid size-11 shrink-0 place-items-center rounded-lg bg-rojo text-lg font-black text-white">{i + 1}</span>
                <div>
                  <h3 className="text-lg font-bold">{s.title}</h3>
                  <p className="mt-1 text-muted">{s.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 lg:grid-cols-[1.3fr_1fr] lg:items-start lg:py-16">
          <div>
            <h2 className="text-3xl font-black tracking-tight">El problema es el mercurio</h2>
            <div className="mt-5 space-y-4 text-lg text-muted">
              <p>La minería ilegal usa mercurio para juntar las partículas finas de oro en pepitas. Una parte termina en el río, en el aire y en el suelo.</p>
              <p>En el agua pasa a los peces, y de ellos a las familias que se alimentan del río. Los niños y las mujeres embarazadas son los más afectados.</p>
              <p className="font-medium text-ink">Encontrar una draga a tiempo permite actuar antes de que el daño se extienda río abajo.</p>
            </div>
          </div>
          <aside className="rounded-xl border border-ambar/40 bg-ambar/10 p-6">
            <h3 className="text-xl font-bold">¿Viste una draga o una zona minera?</h3>
            <p className="mt-2 text-ink/90">
              Denúnciala ante la fiscalía ambiental o la autoridad ambiental de tu región. {BRAND_NAME} te ayuda a vigilar, pero no reemplaza la denuncia oficial.
            </p>
          </aside>
        </div>
      </section>

      <section className="border-t border-line bg-panel">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:py-16">
          <p className="label-caps">Con honestidad</p>
          <h2 className="mt-2 text-3xl font-black tracking-tight">Qué decidimos y qué quedó fuera</h2>
          <ul className="mt-6 max-w-3xl space-y-3">
            {DECISIONS.map((d) => (
              <li key={d} className="flex gap-3 text-ink/90">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-cian" aria-hidden />
                <span>{d}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="px-4 py-12 sm:px-6 lg:py-16">
        <div className="mx-auto max-w-6xl rounded-xl border border-line bg-[radial-gradient(ellipse_at_top,rgba(225,29,46,.18),transparent_70%)] px-6 py-12 text-center">
          <h2 className="text-3xl font-black tracking-tight">Vigila la Amazonía desde tu celular</h2>
          <p className="mx-auto mt-3 max-w-lg text-lg text-muted">Entra con tu número y elige la zona que quieres vigilar.</p>
          <div className="mt-7">{cta}</div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-6xl space-y-5 px-4 py-10 sm:px-6">
          <div className="flex items-center gap-2 font-extrabold">
            <img src="/brand/logo.png" width={32} height={32} alt="" className="size-8" loading="lazy" />
            {BRAND_NAME}
          </div>
          <p className="max-w-xl text-[15px] text-muted">Monitoreo de minería ilegal en la Amazonía con imágenes satelitales.</p>
          <nav aria-label="Legal" className="flex flex-wrap gap-x-5 text-[15px] [&>a]:inline-flex [&>a]:min-h-11 [&>a]:items-center">
            <Link href={PRIVACY_URL} className="underline underline-offset-4">Política de privacidad</Link>
            <Link href={TERMS_URL} className="underline underline-offset-4">Términos y condiciones</Link>
          </nav>
          <p className="text-sm text-muted">{BRAND_NAME} no es una entidad del Estado peruano.</p>
          <p className="text-xs leading-relaxed text-muted/80">
            Fotos:{" "}
            {PHOTO_CREDITS.map((c, i) => (
              <span key={c.href}>
                {c.text} (<a className="underline" href={c.href}>{c.license}</a>){i < PHOTO_CREDITS.length - 1 ? "; " : "."}
              </span>
            ))}
          </p>
        </div>
      </footer>
    </div>
  );
}
