import { LegalPage, LegalSection } from "./LegalPage";
import { COMPANY } from "./company";


const Email = () => (
  <a href={`mailto:${COMPANY.email}`} className="font-medium text-rojo-3 underline underline-offset-2">
    {COMPANY.email}
  </a>
);

export default function PrivacidadPage(_props: { token?: string }) {
  return (
    <LegalPage title="Política de privacidad">
      <p>
        Esta política explica cómo tratamos tus datos personales cuando usas Ojo de Cóndor, conforme a la Ley N.° 29733, Ley de
        Protección de Datos Personales, y su Reglamento aprobado por Decreto Supremo N.° 016-2024-JUS.
      </p>

      <LegalSection title="1. Responsable del tratamiento">
        <p>
          {COMPANY.legalName}, con RUC {COMPANY.ruc} y domicilio en {COMPANY.address}, es responsable de tus datos. Puedes
          escribirnos a <Email />.
        </p>
      </LegalSection>

      <LegalSection title="2. Datos que tratamos">
        <ul>
          <li><strong>Obligatorio:</strong> tu número de celular con WhatsApp. Sin él no podemos darte acceso ni enviarte alertas.</li>
          <li><strong>Técnicos:</strong> cookies necesarias para mantener tu sesión iniciada.</li>
        </ul>
        <p>No pedimos datos sensibles.</p>
      </LegalSection>

      <LegalSection title="3. Para qué usamos tus datos">
        <ul>
          <li>Verificar tu número y darte acceso a Ojo de Cóndor.</li>
          <li>Enviarte por WhatsApp alertas sobre minería ilegal.</li>
        </ul>
        <p>No vendemos tus datos ni los usamos para publicidad de terceros.</p>
      </LegalSection>

      <LegalSection title="4. Base del tratamiento">
        <p>
          Tratamos tus datos con tu consentimiento libre, previo, expreso, informado e inequívoco, que nos das al marcar la
          casilla de aceptación antes de recibir tu código. Puedes revocarlo en cualquier momento.
        </p>
      </LegalSection>

      <LegalSection title="5. Con quién compartimos tus datos">
        <ul>
          <li>Meta Platforms, Inc. (WhatsApp Business), para enviarte el código de acceso y las alertas.</li>
          <li>Proveedores de alojamiento y bases de datos en la nube que almacenan la información por encargo nuestro.</li>
          <li>Autoridades competentes, solo cuando la ley nos lo exija.</li>
        </ul>
        <p>
          Algunos de estos proveedores están fuera del Perú, principalmente en Estados Unidos, por lo que hay flujo
          transfronterizo de datos. Exigimos que apliquen medidas de seguridad adecuadas.
        </p>
      </LegalSection>

      <LegalSection title="6. Banco de datos y conservación">
        <p>
          Tus datos se guardan en bancos de datos personales de {COMPANY.legalName} inscritos ante la Autoridad Nacional de
          Protección de Datos Personales. Los conservamos mientras tengas una cuenta en Ojo de Cóndor. Si pides eliminarla, los
          borramos, salvo lo que debamos conservar por obligación legal.
        </p>
      </LegalSection>

      <LegalSection title="7. Tus derechos">
        <p>
          Puedes ejercer tus derechos de información, acceso, rectificación, cancelación y oposición, y revocar tu
          consentimiento, escribiendo a <Email /> con tu nombre, tu número registrado y una copia de tu documento de identidad.
          Responderemos dentro de los plazos que fija la ley.
        </p>
        <p>
          Si consideras que no atendimos tu solicitud, puedes presentar una reclamación ante la Autoridad Nacional de
          Protección de Datos Personales del Ministerio de Justicia y Derechos Humanos.
        </p>
      </LegalSection>

      <LegalSection title="8. Seguridad">
        <p>
          Aplicamos medidas técnicas y organizativas para proteger tus datos: conexiones cifradas, acceso restringido al
          personal autorizado y códigos de acceso de un solo uso que vencen a los 10 minutos.
        </p>
      </LegalSection>

      <LegalSection title="9. Menores de edad">
        <p>Si tienes menos de 14 años, necesitas la autorización de tu madre, padre o tutor para usar Ojo de Cóndor.</p>
      </LegalSection>

      <LegalSection title="10. Cookies">
        <p>Solo usamos cookies necesarias para iniciar y mantener tu sesión. No usamos cookies de publicidad ni de analítica.</p>
      </LegalSection>

      <LegalSection title="11. Cambios a esta política">
        <p>
          Si cambiamos esta política, publicaremos la nueva versión aquí con su fecha. Si el cambio afecta cómo usamos tus
          datos, te pediremos nuevamente tu consentimiento.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
