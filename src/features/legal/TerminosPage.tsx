import { Link } from "../../router";
import { LegalPage, LegalSection } from "./LegalPage";
import { COMPANY } from "./company";


export default function TerminosPage(_props: { token?: string }) {
  return (
    <LegalPage title="Términos y condiciones">
      <p>Al iniciar sesión en Ojo de Cóndor aceptas estos términos. Léelos con calma: son cortos.</p>

      <LegalSection title="1. Quién presta el servicio">
        <p>
          Ojo de Cóndor es un servicio de {COMPANY.legalName}, con RUC {COMPANY.ruc} y domicilio en {COMPANY.address}. Contacto:{" "}
          <a href={`mailto:${COMPANY.email}`} className="font-medium text-red-400 underline underline-offset-2">{COMPANY.email}</a>.
        </p>
      </LegalSection>

      <LegalSection title="2. Qué es Ojo de Cóndor">
        <p>
          Ojo de Cóndor analiza imágenes satelitales para identificar posible actividad de minería ilegal, como dragas en ríos o
          tajos abiertos, y envía alertas informativas por WhatsApp. El servicio es gratuito y puede cambiar mientras lo
          mejoramos.
        </p>
      </LegalSection>

      <LegalSection title="3. Tu cuenta">
        <ul>
          <li>Inicias sesión con un número de WhatsApp propio y un código que te enviamos.</li>
          <li>Eres responsable de no compartir ese código y de que los datos que nos das sean verdaderos.</li>
        </ul>
      </LegalSection>

      <LegalSection title="4. Uso permitido">
        <p>No puedes usar Ojo de Cóndor para:</p>
        <ul>
          <li>Cometer o facilitar actos ilícitos.</li>
          <li>Amenazar, hostigar o exponer a otras personas.</li>
          <li>Difundir las alertas como si fueran hechos comprobados.</li>
          <li>Intentar acceder sin permiso a nuestros sistemas o afectar su funcionamiento.</li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Naturaleza de las alertas">
        <p>
          Las alertas se generan de forma automática y señalan actividad <strong>posible</strong>. Pueden contener errores u
          omisiones. No constituyen prueba, acusación ni denuncia, y no reemplazan a las autoridades. Si presencias un delito o
          una emergencia, comunícate con la fiscalía, la policía o la autoridad ambiental. No actúes por tu cuenta contra
          ninguna persona.
        </p>
      </LegalSection>

      <LegalSection title="6. Disponibilidad">
        <p>
          Hacemos lo posible para que Ojo de Cóndor funcione siempre, pero no garantizamos que esté disponible sin interrupciones
          ni que detecte toda la actividad minera. Podemos suspender o modificar el servicio cuando sea necesario.
        </p>
      </LegalSection>

      <LegalSection title="7. Propiedad intelectual">
        <p>
          La marca Ojo de Cóndor, su logotipo y el software son de {COMPANY.legalName}. Las imágenes de terceros se usan según sus
          licencias, indicadas en el pie de página.
        </p>
      </LegalSection>

      <LegalSection title="8. Responsabilidad">
        <p>
          En la medida que permita la ley, no somos responsables por decisiones tomadas solo a partir de una alerta. Nada en
          estos términos limita los derechos que te reconoce el Código de Protección y Defensa del Consumidor (Ley N.° 29571).
        </p>
      </LegalSection>

      <LegalSection title="9. Datos personales">
        <p>
          Tratamos tus datos según nuestra{" "}
          <Link href="/privacidad" className="font-medium text-red-400 underline underline-offset-2">Política de privacidad</Link>.
        </p>
      </LegalSection>

      <LegalSection title="10. Fin del servicio">
        <p>
          Puedes dejar de usar Ojo de Cóndor y pedir que eliminemos tu cuenta cuando quieras. Podemos cerrar cuentas que incumplan
          estos términos.
        </p>
      </LegalSection>

      <LegalSection title="11. Cambios y ley aplicable">
        <p>
          Si cambiamos estos términos, publicaremos la nueva versión aquí con su fecha. Estos términos se rigen por las leyes
          del Perú, y cualquier controversia se resolverá ante los jueces y tribunales de Lima.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
